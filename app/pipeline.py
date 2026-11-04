"""Derived-data pipeline: events -> sessions -> people -> order attribution.

refresh() is idempotent and incremental where it is cheap to be:
  * sessions are rebuilt ONLY for visitors (anonymous_id) that received new events ("dirty"),
    so a late event for 1 Sept re-splits just that visitor's sessions;
  * identity + attribution are recomputed globally (a few ms per 1k orders) because one new
    email link can re-credit orders of any of the person's other devices.
Everything is computed from a consistent read snapshot, then swapped in ONE write transaction,
so dashboards never see half-built tables.
"""
from __future__ import annotations

import hashlib
import itertools
import logging
import threading
import time
from datetime import UTC, datetime

from . import attribution as A
from . import config as C
from . import db
from . import normalize as N

log = logging.getLogger("pipeline")
_refresh_lock = threading.Lock()
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


# ----------------------------------------------------------------------------- sessions
def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


def build_sessions(anon: str, events: list) -> list[dict]:
    """events: rows sorted by ts_ms. New session after >30 min of inactivity."""
    out, cur, last = [], [], None
    for e in events:
        if last is not None and e["ts_ms"] - last > C.SESSION_GAP_MS:
            out.append(cur)
            cur = []
        cur.append(e)
        last = e["ts_ms"]
    if cur:
        out.append(cur)
    rows = []
    for i, evs in enumerate(out):
        first = next((e for e in evs if e["is_touch"]), None)  # session channel = its first marketing touch
        start, end = evs[0]["ts_ms"], evs[-1]["ts_ms"]
        landing = next((e["page_url"] for e in evs if e["event_name"] == "page_view"), evs[0]["page_url"])
        names = {e["event_name"] for e in evs}
        rows.append({
            "session_id": f"{anon}:{i + 1}", "anonymous_id": anon, "day": _dt(start).date(),
            "start_ms": start, "end_ms": end, "start_ts": _dt(start), "end_ts": _dt(end),
            "duration_s": (end - start) / 1000.0, "n_events": len(evs),
            "n_page_views": sum(e["event_name"] == "page_view" for e in evs),
            "channel": first["channel"] if first else C.DIRECT,
            "utm_campaign": first["utm_campaign"] if first else None, "landing_url": landing,
            "has_atc": "add_to_cart" in names, "has_checkout": "checkout_started" in names,
            "has_purchase": any(e["event_name"] == "purchase" and not str(e["order_id"] or "").upper().startswith("TEST")
                                for e in evs),
        })
    return rows


# ----------------------------------------------------------------------------- identity
class _UF:
    def __init__(self):
        self.p: dict[str, str] = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)  # smallest label is the root => stable ids


def _person_id(root: str) -> str:
    return "p_" + hashlib.sha1(root.encode()).hexdigest()[:12]


def build_identity(anons, pairs, orders, purchase_links):
    """Connected components over: anon<->email (any identifying event), order->email, order->purchase-event anon.
    This is how 'which events and orders belong to the same person' is answered, across devices."""
    uf = _UF()
    for a in anons:
        uf.find("a:" + a)
    for a, e in pairs:
        uf.union("a:" + a, "e:" + e)
    for oid, email in orders:
        if email:
            uf.find("e:" + email)
        anon = purchase_links.get(oid)
        if anon:
            if email:
                uf.union("a:" + anon, "e:" + email)
            else:
                uf.find("a:" + anon)
    return {n: _person_id(uf.find(n)) for n in list(uf.p)}


# ----------------------------------------------------------------------------- refresh
def pending(conn=None) -> bool:
    """True while ingested data has not been folded into the derived tables yet."""
    if conn is None:
        with db.read() as c:
            return pending(c)
    behind = db.get_gen(conn) > int(db.get_meta(conn, "attr_done", 0))
    return behind or conn.execute("SELECT EXISTS (SELECT 1 FROM dirty_anons) AS d").fetchone()["d"]


def refresh(full: bool = False) -> dict:
    with _refresh_lock:
        t0 = time.perf_counter()
        with db.read() as r:  # one consistent snapshot for every read below
            snap_gen = db.get_gen(r)
            if full:
                dirty = [(x["anonymous_id"], None) for x in r.execute("SELECT DISTINCT anonymous_id FROM events WHERE NOT is_bot")]
            else:
                dirty = [(x["anonymous_id"], x["gen"]) for x in r.execute("SELECT anonymous_id, gen FROM dirty_anons")]
            dirty_set = {a for a, _ in dirty}

            # 1) sessions for dirty visitors
            sessions: list[dict] = []
            if dirty_set:
                if full or len(dirty_set) > 2000:
                    q = ("SELECT anonymous_id, event_id, event_name, ts_ms, page_url, channel, utm_campaign, is_touch, order_id "
                         "FROM events WHERE NOT is_bot ORDER BY anonymous_id, ts_ms, event_id")
                    rows = (x for x in r.execute(q) if full or x["anonymous_id"] in dirty_set)
                else:
                    q = ("SELECT e.anonymous_id, e.event_id, e.event_name, e.ts_ms, e.page_url, e.channel, e.utm_campaign, "
                         "e.is_touch, e.order_id FROM events e JOIN dirty_anons d USING (anonymous_id) "
                         "WHERE NOT e.is_bot ORDER BY e.anonymous_id, e.ts_ms, e.event_id")
                    rows = r.execute(q)
                for anon, grp in itertools.groupby(rows, key=lambda x: x["anonymous_id"]):
                    sessions += build_sessions(anon, list(grp))

            # 2) identity (global)
            anons = [x["anonymous_id"] for x in r.execute("SELECT DISTINCT anonymous_id FROM events WHERE NOT is_bot")]
            pairs = [(x["anonymous_id"], x["email_hash"]) for x in r.execute(
                "SELECT DISTINCT anonymous_id, email_hash FROM events WHERE NOT is_bot AND email_hash IS NOT NULL")]
            orders = [dict(x) for x in r.execute("SELECT order_id, email_hash, created_ms FROM orders")]
            links = {x["order_id"]: x["anonymous_id"] for x in r.execute(
                "SELECT order_id, anonymous_id FROM events WHERE event_name = 'purchase' AND NOT is_bot "
                "AND order_id IS NOT NULL ORDER BY ts_ms DESC")}
            pmap = build_identity(anons, pairs, [(o["order_id"], o["email_hash"]) for o in orders], links)
            anon_to_person = {n[2:]: p for n, p in pmap.items() if n.startswith("a:")}
            order_person = {}
            for o in orders:
                order_person[o["order_id"]] = (pmap.get("e:" + o["email_hash"]) if o["email_hash"] else None) \
                    or (pmap.get("a:" + links[o["order_id"]]) if o["order_id"] in links else None)

            # 3) attribution (global; both models at the default window)
            touches = A.load_touches(r, anon_to_person)
            journey = set(anon_to_person.values())
            attr = []
            for m in A.MODELS:
                attr += A.attribute(orders, touches, order_person, journey, C.ATTRIBUTION_WINDOW_DAYS, m)

        # 4) atomic swap: readers see either the old derived tables or the new ones, never a mix
        with db.write() as w:
            if full:
                w.execute("DELETE FROM sessions")
            else:
                w.execute("DELETE FROM sessions WHERE anonymous_id = ANY(%s)", (sorted(dirty_set),))
            db.executemany(w, 
                """INSERT INTO sessions (session_id, anonymous_id, day, start_ms, end_ms, start_ts, end_ts, duration_s,
                     n_events, n_page_views, channel, utm_campaign, landing_url, has_atc, has_checkout, has_purchase)
                   VALUES (%(session_id)s, %(anonymous_id)s, %(day)s, %(start_ms)s, %(end_ms)s, %(start_ts)s, %(end_ts)s,
                     %(duration_s)s, %(n_events)s, %(n_page_views)s, %(channel)s, %(utm_campaign)s, %(landing_url)s,
                     %(has_atc)s, %(has_checkout)s, %(has_purchase)s)""", sessions)
            w.execute("DELETE FROM person_map")
            db.executemany(w, "INSERT INTO person_map (node, person_id) VALUES (%s, %s)", list(pmap.items()))
            w.execute("UPDATE sessions s SET person_id = m.person_id FROM person_map m WHERE m.node = 'a:' || s.anonymous_id")
            w.execute("DELETE FROM order_attribution")
            db.executemany(w, 
                """INSERT INTO order_attribution (order_id, model, channel, campaign, touch_event_id, touch_ms, days_to_order,
                     person_id, n_touches, reason, window_days)
                   VALUES (%(order_id)s, %(model)s, %(channel)s, %(campaign)s, %(touch_event_id)s, %(touch_ms)s,
                     %(days_to_order)s, %(person_id)s, %(n_touches)s, %(reason)s, %(window_days)s)""", attr)
            # clear only what we processed: events that arrived mid-refresh keep a newer gen
            db.executemany(w, "DELETE FROM dirty_anons WHERE anonymous_id = %s AND gen = %s", [(a, g) for a, g in dirty if g is not None])
            if full:
                w.execute("DELETE FROM dirty_anons WHERE gen <= %s", (snap_gen,))
            db.set_meta(w, "attr_done", snap_gen)
            n = int(db.get_meta(w, "refresh_count", 0)) + 1
            ms = round((time.perf_counter() - t0) * 1000)
            db.set_meta(w, "refresh_count", n)
            db.set_meta(w, "last_refresh_at", N.iso(datetime.now(UTC)))
            db.set_meta(w, "last_refresh_ms", ms)
            db.set_meta(w, "last_refresh_dirty", len(dirty_set))
        log.info("refresh #%s: %s dirty visitors, %s sessions, %s orders in %s ms", n, len(dirty_set), len(sessions),
                 len(orders), ms)
        return {"refresh_count": n, "dirty_visitors": len(dirty_set), "sessions_written": len(sessions),
                "orders": len(orders), "ms": ms}


# ----------------------------------------------------------------------------- background worker
def request_refresh() -> None:
    _wake.set()


def _worker() -> None:
    while not _stop.is_set():
        _wake.wait(timeout=30)
        if _stop.is_set():
            break
        if not _wake.is_set() and not pending():
            continue
        first = time.monotonic()
        while True:  # debounce: wait for ingest to go quiet, but never longer than MAX_WAIT
            _wake.clear()
            if _wake.wait(timeout=C.REFRESH_DEBOUNCE_S) and time.monotonic() - first < C.REFRESH_MAX_WAIT_S:
                continue
            break
        try:
            refresh()
        except Exception:  # keep the worker alive; the next ingest retries
            log.exception("refresh failed")
            time.sleep(2)
            _wake.set()


def start() -> None:
    global _thread
    _stop.clear()
    _thread = threading.Thread(target=_worker, name="refresh-worker", daemon=True)
    _thread.start()
    _wake.set()  # catch up on anything that was pending at startup


def stop() -> None:
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=5)
