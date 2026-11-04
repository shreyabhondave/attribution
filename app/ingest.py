"""HTTP ingestion: POST /collect, POST /webhooks/orders, POST /ad-spend.

Design rules
  * Ingestion NEVER computes anything heavy. It validates, normalises, stores raw facts
    idempotently, marks what became stale and returns 202. The pipeline rebuilds derived data.
  * Every endpoint is idempotent (safe to retry / replay) and order-independent
    (an out-of-order webhook or a late event cannot corrupt state).
  * Bad rows are counted, never silently dropped (see /api/quality).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from . import config as C
from . import db, pipeline
from . import normalize as N

router = APIRouter()


def _f(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _s(v) -> str | None:
    v = None if v is None else str(v).strip()
    return v or None


# ------------------------------------------------------------------------------ events
def store_event(conn, e: Any) -> tuple[str, str | None]:
    """-> ('inserted' | 'duplicate' | 'rejected', anonymous_id to mark dirty or None)"""
    if not isinstance(e, dict):
        return "rejected", None
    event_id, name, anon = _s(e.get("event_id")), _s(e.get("event_name")), _s(e.get("anonymous_id"))
    if not (event_id and name and anon):
        return "rejected", None
    received = N.parse_ts(e.get("received_at")) or datetime.now(UTC)
    ts_raw = e.get("ts")
    eff, src = N.effective_ts(N.parse_ts(ts_raw), received)
    name = name.lower()
    ua = _s(e.get("user_agent"))
    bot = N.is_bot(ua)
    page_url, referrer = _s(e.get("page_url")), _s(e.get("referrer"))
    c = N.classify(page_url, referrer)
    is_touch = bool(c["is_touch"] and name == "page_view" and not bot)
    email = (_s(e.get("email_hash")) or "").lower() or None
    cur = conn.execute(
        """INSERT INTO events (event_id, event_name, anonymous_id, email_hash, ts_raw, ts_format, received_at,
             ts_utc, ts_ms, ts_source, page_url, referrer, user_agent, ip, value, currency, order_id, is_bot,
             channel, utm_source, utm_medium, utm_campaign, click_id_type, is_touch)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (event_id) DO NOTHING""",
        (event_id, name, anon, email, None if ts_raw is None else str(ts_raw), N.ts_format(ts_raw), received,
         eff, N.to_ms(eff), src, page_url, referrer, ua, _s(e.get("ip")), _f(e.get("value")), _s(e.get("currency")),
         _s(e.get("order_id")), bot, c["channel"], c["utm_source"], c["utm_medium"], c["utm_campaign"],
         c["click_id_type"], is_touch))
    if cur.rowcount == 0:
        return "duplicate", None
    return "inserted", (None if bot else anon)


def _batch(payload: Any) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        return payload["events"]
    return [payload]


@router.post("/collect", status_code=202)
def collect(payload: Any = Body(...)):
    items = _batch(payload)
    res = {"inserted": 0, "duplicate": 0, "rejected": 0}
    dirty: set[str] = set()
    with db.write() as conn:
        for e in items:
            status, anon = store_event(conn, e)
            res[status] += 1
            if anon:
                dirty.add(anon)
        if dirty:
            gen = db.next_gen(conn)
            # sorted => concurrent batches always lock the same rows in the same order (no deadlocks)
            db.executemany(conn, "INSERT INTO dirty_anons (anonymous_id, gen) VALUES (%s, %s) "
                             "ON CONFLICT (anonymous_id) DO UPDATE SET gen = EXCLUDED.gen", [(a, gen) for a in sorted(dirty)])
        db.bump(conn, "events_received", len(items))
        for k in ("duplicate", "rejected"):
            if res[k]:
                db.bump(conn, f"events_{k}", res[k])
    if res["rejected"] and len(items) == 1:
        raise HTTPException(422, "event needs event_id, event_name and anonymous_id")
    if res["inserted"]:
        pipeline.request_refresh()
    return res


# ------------------------------------------------------------------------------ orders
def store_order(conn, w: Any) -> str:
    """-> 'inserted' | 'updated' | 'duplicate' | 'stale' | 'ignored_test' | 'rejected'"""
    if not isinstance(w, dict):
        return "rejected"
    oid, status = _s(w.get("order_id")), (_s(w.get("financial_status")) or "").lower()
    created, updated = N.parse_ts(w.get("created_at")), N.parse_ts(w.get("updated_at"))
    total, cur = _f(w.get("total")), (_s(w.get("currency")) or "INR").upper()
    if not (oid and status and created and updated) or total is None or total < 0 or cur not in C.FX_TO_INR:
        return "rejected"
    if oid.upper().startswith("TEST"):
        return "ignored_test"
    email = (_s(w.get("email_hash")) or "").lower() or None
    ins = conn.execute(
        "INSERT INTO order_webhooks (order_id, updated_at, financial_status, email_hash, created_at, total, currency)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (oid, updated, status, email, created, total, cur))
    if ins.rowcount == 0:
        return "duplicate"
    # newest updated_at wins, regardless of arrival order (webhooks can be delivered out of order).
    # `xmax = 0` is true only for a freshly inserted row, which distinguishes insert from update atomically.
    up = conn.execute(
        """INSERT INTO orders (order_id, email_hash, created_at, created_day, created_ms, updated_at, financial_status,
                               total, currency, total_inr)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (order_id) DO UPDATE SET email_hash = EXCLUDED.email_hash, created_at = EXCLUDED.created_at,
             created_day = EXCLUDED.created_day, created_ms = EXCLUDED.created_ms, updated_at = EXCLUDED.updated_at,
             financial_status = EXCLUDED.financial_status, total = EXCLUDED.total, currency = EXCLUDED.currency,
             total_inr = EXCLUDED.total_inr
           WHERE EXCLUDED.updated_at >= orders.updated_at
           RETURNING (xmax = 0) AS inserted""",
        (oid, email, created, created.date(), N.to_ms(created), updated, status, total, cur,
         round(total * C.FX_TO_INR[cur], 2))).fetchone()
    if up is None:
        return "stale"
    return "inserted" if up["inserted"] else "updated"


@router.post("/webhooks/orders", status_code=202)
def order_webhook(payload: Any = Body(...)):
    items = payload if isinstance(payload, list) else [payload]
    res: dict[str, int] = {}
    with db.write() as conn:
        for w in items:
            r = store_order(conn, w)
            res[r] = res.get(r, 0) + 1
        if res.get("inserted") or res.get("updated"):
            db.next_gen(conn)  # bumps the change counter => derived tables are now stale
        db.bump(conn, "webhooks_received", len(items))
        for k, v in sorted(res.items()):
            if k in ("duplicate", "stale", "rejected", "ignored_test"):
                db.bump(conn, f"webhooks_{k}", v)
    if res.get("rejected") and len(items) == 1:
        raise HTTPException(422, "webhook needs order_id, financial_status, created_at, updated_at, total, known currency")
    if res.get("inserted") or res.get("updated"):
        pipeline.request_refresh()
    return res


# ------------------------------------------------------------------------------ ad spend
def store_spend(conn, r: Any) -> str:
    if not isinstance(r, dict):
        return "rejected"
    d, plat, camp = N.parse_ts(r.get("date")), (_s(r.get("platform")) or "").lower(), (_s(r.get("campaign")) or "").lower()
    spend, cur = _f(r.get("spend")), (_s(r.get("currency")) or "INR").upper()
    pulled = N.parse_ts(r.get("pulled_at"))
    if not (d and plat and camp and pulled) or spend is None or spend < 0:
        return "rejected"
    if cur != C.REPORTING_CURRENCY:
        if cur not in C.FX_TO_INR:
            return "rejected"
        spend, cur = round(spend * C.FX_TO_INR[cur], 2), C.REPORTING_CURRENCY
    ins = conn.execute("INSERT INTO ad_spend_pulls (date, platform, campaign, spend, currency, pulled_at)"
                       " VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (d.date(), plat, camp, spend, cur, pulled))
    return "inserted" if ins.rowcount else "duplicate"


@router.post("/ad-spend", status_code=202)
def ad_spend(payload: Any = Body(...)):
    items = payload if isinstance(payload, list) else [payload]
    res = {"inserted": 0, "duplicate": 0, "rejected": 0}
    with db.write() as conn:
        for r in items:
            res[store_spend(conn, r)] += 1
        db.bump(conn, "spend_received", len(items))
        if res["rejected"]:
            db.bump(conn, "spend_rejected", res["rejected"])
    if res["rejected"] and len(items) == 1:
        raise HTTPException(422, "ad spend row needs date, platform, campaign, spend, pulled_at")
    return res
