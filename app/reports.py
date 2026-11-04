"""Read-side queries. Every figure is derived from stored rows, and the quality report lists
what was excluded or corrected so any number can be traced back.

Money rules (the contract behind every revenue number)
  * Revenue = orders whose LATEST webhook status is 'paid', in INR (USD x 84), booked on the
    order's created_at UTC day. Refunded / cancelled orders are shown separately, never as revenue.
    So a refund arriving in October lowers September revenue (the past really does change).
  * ROAS = attributed net revenue / ad spend (spend = newest pull per day+campaign). Channels
    without spend (Email, Organic, Direct) have no ROAS (shown as '-').
"""
from __future__ import annotations

import re
import statistics
from datetime import date, timedelta

from . import attribution as A
from . import config as C
from . import db

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NO_CAMPAIGN = "(no campaign tag)"


def r2(x):
    return None if x is None else round(x, 2)


def valid_date(s: str | None) -> str | None:
    if s is None:
        return None
    if not _DATE.match(s):
        raise ValueError(f"bad date '{s}', expected YYYY-MM-DD")
    date.fromisoformat(s)
    return s


# ------------------------------------------------------------------------------ status
def status(conn) -> dict:
    cnt = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM counters")}
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM meta")}
    def one(q: str):
        return conn.execute(q).fetchone()[0]

    days = [d for d in (one("SELECT MIN(created_day)::text FROM orders"), one("SELECT MIN(date)::text FROM ad_spend_current"),
                        one("SELECT MIN(day)::text FROM sessions")) if d]
    days_hi = [d for d in (one("SELECT MAX(created_day)::text FROM orders"), one("SELECT MAX(date)::text FROM ad_spend_current"),
                           one("SELECT MAX(day)::text FROM sessions")) if d]
    gen, done = db.get_gen(conn), int(meta.get("attr_done", 0))
    dirty = one("SELECT COUNT(*) FROM dirty_anons")
    return {
        "data_from": min(days) if days else None, "data_to": max(days_hi) if days_hi else None,
        "events_stored": one("SELECT COUNT(*) FROM events"), "orders_stored": one("SELECT COUNT(*) FROM orders"),
        "spend_rows": one("SELECT COUNT(*) FROM ad_spend_current"), "sessions": one("SELECT COUNT(*) FROM sessions"),
        "counters": cnt, "pending_refresh": gen > done or dirty > 0, "pending_visitors": dirty,
        "last_refresh_at": meta.get("last_refresh_at"), "last_refresh_ms": int(meta.get("last_refresh_ms", 0) or 0),
        "refresh_count": int(meta.get("refresh_count", 0)),
        "attribution_window_days": C.ATTRIBUTION_WINDOW_DAYS,
        "version": f"{meta.get('refresh_count', 0)}-{gen}-{cnt.get('spend_received', 0)}",
    }


# ------------------------------------------------------------------------------ core join
def _attr_map(conn, model: str, window: int) -> dict:
    if model not in A.MODELS:
        raise ValueError(f"model must be one of {A.MODELS}")
    if window == C.ATTRIBUTION_WINDOW_DAYS:
        return {r["order_id"]: dict(r) for r in conn.execute("SELECT * FROM order_attribution WHERE model = %s", (model,))}
    return {r["order_id"]: r for r in A.attribution_for_window(conn, window, model)}


def orders_in_range(conn, frm: str, to: str, model: str, window: int) -> list[dict]:
    amap = _attr_map(conn, model, window)
    out = []
    for o in conn.execute("SELECT order_id, created_at, created_day::text AS day, financial_status, total, currency, total_inr, email_hash "
                          "FROM orders WHERE created_day BETWEEN %s AND %s ORDER BY created_at", (frm, to)):
        a = amap.get(o["order_id"]) or {}
        out.append({"order_id": o["order_id"], "day": o["day"], "created_at": o["created_at"],
                    "status": o["financial_status"], "total": o["total"], "currency": o["currency"],
                    "revenue_inr": o["total_inr"], "channel": a.get("channel", C.DIRECT), "campaign": a.get("campaign"),
                    "reason": a.get("reason", "no_journey"), "days_to_order": a.get("days_to_order"),
                    "n_touches": a.get("n_touches", 0), "person_id": a.get("person_id")})
    return out


def _spend_rows(conn, frm, to):
    return conn.execute("SELECT date::text AS date, platform, campaign, spend FROM ad_spend_current WHERE date BETWEEN %s AND %s",
                        (frm, to)).fetchall()


def _blank():
    return {"orders": 0, "revenue": 0.0, "gross_orders": 0, "refunded_orders": 0, "refunded_revenue": 0.0,
            "cancelled_orders": 0, "cancelled_value": 0.0, "spend": 0.0}


def _tally(a: dict, o: dict) -> None:
    a["gross_orders"] += 1
    s = o["status"]
    if s == "paid":
        a["orders"] += 1
        a["revenue"] += o["revenue_inr"]
    elif s == "refunded":
        a["refunded_orders"] += 1
        a["refunded_revenue"] += o["revenue_inr"]
    elif s == "cancelled":
        a["cancelled_orders"] += 1
        a["cancelled_value"] += o["revenue_inr"]


def _finish(a: dict) -> dict:
    a["roas"] = r2(a["revenue"] / a["spend"]) if a["spend"] > 0 else None
    a["aov"] = r2(a["revenue"] / a["orders"]) if a["orders"] else None
    a["cpa"] = r2(a["spend"] / a["orders"]) if a["orders"] and a["spend"] > 0 else None
    for k in ("revenue", "refunded_revenue", "cancelled_value", "spend"):
        a[k] = r2(a[k])
    return a


# ------------------------------------------------------------------------------ channels
def channels(conn, frm, to, model, window) -> dict:
    orders = orders_in_range(conn, frm, to, model, window)
    agg: dict[str, dict] = {}
    for o in orders:
        _tally(agg.setdefault(o["channel"], _blank()), o)
    for s in _spend_rows(conn, frm, to):
        ch = C.PLATFORM_TO_CHANNEL.get(s["platform"], s["platform"])
        agg.setdefault(ch, _blank())["spend"] += s["spend"]
    sess = {r["channel"]: dict(r) for r in conn.execute(
        "SELECT channel, COUNT(*) AS sessions, COUNT(*) FILTER (WHERE has_purchase) AS purchase_sessions FROM sessions "
        "WHERE day BETWEEN %s AND %s GROUP BY channel",
        (frm, to))}
    for ch in sess:
        agg.setdefault(ch, _blank())
    total_rev = sum(a["revenue"] for a in agg.values())
    rows = []
    for ch in sorted(agg, key=lambda c: (-agg[c]["revenue"], c)):
        a = agg[ch]
        a.update(channel=ch, is_paid=ch in C.PAID_CHANNELS,
                 sessions=sess.get(ch, {}).get("sessions", 0), purchase_sessions=sess.get(ch, {}).get("purchase_sessions") or 0)
        a["session_cvr"] = r2(100 * a["purchase_sessions"] / a["sessions"]) if a["sessions"] else None
        a["revenue_share"] = r2(100 * a["revenue"] / total_rev) if total_rev else 0
        rows.append(_finish(a))
    tot = _blank()
    for a in agg.values():
        for k in tot:
            tot[k] += a.get(k, 0)
    paid_rev = sum(agg[c]["revenue"] for c in agg if c in C.PAID_CHANNELS)
    paid_spend = sum(agg[c]["spend"] for c in agg if c in C.PAID_CHANNELS)
    direct_rev = agg.get(C.DIRECT, {}).get("revenue", 0)
    _finish(tot)
    tot.update(blended_roas=tot.pop("roas"), paid_revenue=r2(paid_rev),
               paid_roas=r2(paid_rev / paid_spend) if paid_spend else None,
               attributed_share=r2(100 * (total_rev - direct_rev) / total_rev) if total_rev else None)
    return {"params": {"from": frm, "to": to, "model": model, "window_days": window}, "rows": rows, "totals": tot}


# ------------------------------------------------------------------------------ daily
def _days(frm, to):
    d, end = date.fromisoformat(frm), date.fromisoformat(to)
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def daily(conn, frm, to, model, window) -> dict:
    orders = orders_in_range(conn, frm, to, model, window)
    per = {d: {"total": _blank(), "by_channel": {}} for d in _days(frm, to)}
    chans = set()
    for o in orders:
        d = per[o["day"]]
        _tally(d["total"], o)
        _tally(d["by_channel"].setdefault(o["channel"], _blank()), o)
        chans.add(o["channel"])
    for s in _spend_rows(conn, frm, to):
        ch = C.PLATFORM_TO_CHANNEL.get(s["platform"], s["platform"])
        d = per[s["date"]]
        d["total"]["spend"] += s["spend"]
        d["by_channel"].setdefault(ch, _blank())["spend"] += s["spend"]
        chans.add(ch)
    order = [c for c in C.CHANNEL_ORDER if c in chans] + sorted(chans - set(C.CHANNEL_ORDER))
    days = []
    for d, v in per.items():
        days.append({"date": d, **_finish(v["total"]),
                     "by_channel": {c: _finish(v["by_channel"].get(c) or _blank()) for c in order}})
    return {"params": {"from": frm, "to": to, "model": model, "window_days": window}, "channels": order, "days": days}


# ------------------------------------------------------------------------------ campaigns
def campaigns(conn, frm, to, model, window) -> dict:
    agg: dict[tuple, dict] = {}
    for o in orders_in_range(conn, frm, to, model, window):
        if o["channel"] in C.PAID_CHANNELS or o["campaign"]:
            _tally(agg.setdefault((o["channel"], o["campaign"] or NO_CAMPAIGN), _blank()), o)
    for s in _spend_rows(conn, frm, to):
        ch = C.PLATFORM_TO_CHANNEL.get(s["platform"], s["platform"])
        agg.setdefault((ch, s["campaign"]), _blank())["spend"] += s["spend"]
    rows = []
    for (ch, camp), a in agg.items():
        a.update(channel=ch, campaign=camp)
        rows.append(_finish(a))
    rows.sort(key=lambda r: (-r["spend"], -r["revenue"]))
    return {"params": {"from": frm, "to": to, "model": model, "window_days": window}, "rows": rows}


# ------------------------------------------------------------------------------ traffic / funnel
def funnel(conn, frm, to) -> dict:
    f = dict(conn.execute(
        "SELECT COUNT(*) AS sessions, COUNT(*) FILTER (WHERE has_atc) AS add_to_cart, COUNT(*) FILTER (WHERE has_checkout) AS checkout, "
        "COUNT(*) FILTER (WHERE has_purchase) AS purchase, COUNT(DISTINCT person_id) AS visitors FROM sessions WHERE day BETWEEN %s AND %s",
        (frm, to)).fetchone())
    by_day = {r["day"]: dict(r) for r in conn.execute(
        "SELECT day::text AS day, COUNT(*) AS sessions, COUNT(*) FILTER (WHERE has_purchase) AS purchase_sessions "
        "FROM sessions WHERE day BETWEEN %s AND %s GROUP BY day",
        (frm, to))}
    days = [{"date": d, "sessions": by_day.get(d, {}).get("sessions", 0),
             "purchase_sessions": by_day.get(d, {}).get("purchase_sessions") or 0} for d in _days(frm, to)]
    return {"funnel": f, "days": days}


# ------------------------------------------------------------------------------ days to convert
BUCKETS = [("Same day", 0, 1), ("1 day", 1, 2), ("2 days", 2, 3), ("3-6 days", 3, 7), ("7-13 days", 7, 14),
           ("14-29 days", 14, 30), ("30+ days", 30, 10 ** 6)]


def conversion_lag(conn, frm, to) -> dict:
    first = {r["person_id"]: r["first_ms"] for r in conn.execute(
        "SELECT person_id, MIN(start_ms) AS first_ms FROM sessions WHERE person_id IS NOT NULL GROUP BY person_id")}
    lags, no_journey = [], 0
    for r in conn.execute("SELECT o.created_ms, a.person_id FROM orders o JOIN order_attribution a "
                          "ON a.order_id=o.order_id AND a.model='last_click' "
                          "WHERE o.financial_status = 'paid' AND o.created_day BETWEEN %s AND %s", (frm, to)):
        fm = first.get(r["person_id"])
        if fm is None:
            no_journey += 1
        else:
            lags.append(max(r["created_ms"] - fm, 0) / 86_400_000)
    hist = [{"bucket": n, "orders": sum(lo <= x < hi for x in lags)} for n, lo, hi in BUCKETS]
    return {"histogram": hist, "orders_with_journey": len(lags), "orders_without_journey": no_journey,
            "median_days": r2(statistics.median(lags)) if lags else None,
            "mean_days": r2(sum(lags) / len(lags)) if lags else None,
            "share_within_window": r2(100 * sum(x <= C.ATTRIBUTION_WINDOW_DAYS for x in lags) / len(lags)) if lags else None}


# ------------------------------------------------------------------------------ order explorer
def order_list(conn, frm, to, model, window, channel=None, status_=None, q=None, limit=50, offset=0) -> dict:
    rows = orders_in_range(conn, frm, to, model, window)
    if channel:
        rows = [r for r in rows if r["channel"] == channel]
    if status_:
        rows = [r for r in rows if r["status"] == status_]
    if q:
        rows = [r for r in rows if q.lower() in r["order_id"].lower()]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return {"total": len(rows), "rows": rows[offset:offset + limit]}


def order_explain(conn, order_id: str, window: int) -> dict | None:
    o = conn.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,)).fetchone()
    if not o:
        return None
    attrs = {m: _attr_map(conn, m, window).get(order_id) for m in A.MODELS}
    person = (attrs["last_click"] or {}).get("person_id")
    devices, touches = [], []
    if person:
        devices = [dict(r) for r in conn.execute(
            "SELECT anonymous_id, COUNT(*) AS sessions, MIN(start_ts) AS first_seen, MAX(end_ts) AS last_seen FROM sessions "
            "WHERE person_id = %s GROUP BY anonymous_id", (person,))]
        win_start = o["created_ms"] - window * 86_400_000
        chosen = {m: (attrs[m] or {}).get("touch_event_id") for m in A.MODELS}
        for t in conn.execute(
                "SELECT e.event_id, e.ts_utc, e.ts_ms, e.channel, e.utm_campaign, e.anonymous_id, e.page_url, e.referrer "
                "FROM events e JOIN person_map m ON m.node = 'a:' || e.anonymous_id WHERE m.person_id = %s AND e.is_touch "
                "AND NOT e.is_bot AND e.ts_ms <= %s ORDER BY e.ts_ms DESC LIMIT 60", (person, o["created_ms"] + C.ORDER_TIME_TOLERANCE_MS)):
            touches.append({**dict(t), "in_window": t["ts_ms"] >= win_start,
                            "is_last_click": t["event_id"] == chosen["last_click"],
                            "is_first_click": t["event_id"] == chosen["first_click"]})
    webhooks = [dict(r) for r in conn.execute("SELECT updated_at, financial_status, total, currency FROM order_webhooks "
                                              "WHERE order_id = %s ORDER BY updated_at", (order_id,))]
    return {"order": dict(o), "attribution": attrs, "person_id": person, "devices": devices, "touches": touches,
            "webhook_history": webhooks, "window_days": window}


# ------------------------------------------------------------------------------ data quality
def quality(conn) -> dict:
    def one(q: str, *args):
        # params=None (not an empty tuple) so literal % in LIKE patterns is not treated as a placeholder
        return conn.execute(q, args or None).fetchone()[0] or 0

    cnt = {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM counters")}
    ev_total = one("SELECT COUNT(*) FROM events")
    items = []

    def add(group, title, count, detail, action, level="info", extra=None):
        items.append({"group": group, "title": title, "count": count, "detail": detail, "action": action,
                      "level": level, **({"extra": extra} if extra else {})})

    # events
    add("Events", "Duplicate event deliveries rejected", cnt.get("events_duplicate", 0),
        "An event_id that was already stored arrived again: pixel retries (later received_at, identical content) "
        "and any operator replay of a file. This counts deliveries since the last reset, not distinct events.",
        "Deduplicated on event_id; first delivery kept. Makes every replay idempotent.", "fix")
    bots = one("SELECT COUNT(*) FROM events WHERE is_bot")
    bot_purchases = one("SELECT COUNT(*) FROM events WHERE is_bot AND event_name = 'purchase'")
    add("Events", "Bot / crawler events", bots,
        f"{one('SELECT COUNT(DISTINCT anonymous_id) FROM events WHERE is_bot')} visitors using HeadlessChrome, python-requests or AhrefsBot; "
        f"{bot_purchases} of their events were purchases.",
        "Stored but excluded from sessions, identity and attribution.", "exclude")
    for src, label in (("received_future", "ahead of the server clock by >5 min (e.g. year 2036)"),
                       ("received_stale", "older than 7 days vs. receive time (e.g. year 2025)")):
        add("Events", f"Impossible device timestamps ({src.split('_')[1]})", one("SELECT COUNT(*) FROM events WHERE ts_source = %s", src),
            f"Device clock {label}.", "Event time replaced by the server's received_at.", "fix")
    add("Events", "Late-arriving events (1h-7d)", one("SELECT COUNT(*) FROM events WHERE ts_source = 'device' AND EXTRACT(EPOCH FROM (received_at - ts_utc)) > 3600"),
        "Pixel batched/offline: device time is plausible but the server received it hours-days later.",
        "Kept on DEVICE time, so the visitor's sessions and any affected order attribution are re-derived. This is how the past changes.", "fix")
    fm = {r["ts_format"]: r["n"] for r in conn.execute("SELECT ts_format, COUNT(*) AS n FROM events GROUP BY ts_format")}
    add("Events", "Mixed timestamp formats", fm.get("epoch", 0) + fm.get("iso_offset", 0),
        f"{fm.get('epoch', 0)} epoch-millisecond values and {fm.get('iso_offset', 0)} ISO values with a +05:30 offset (rest are UTC 'Z').",
        "Everything normalised to UTC.", "fix")
    add("Events", "Click-id-only landings (no utm tags)", one("SELECT COUNT(*) FROM events WHERE is_touch AND utm_source IS NULL AND click_id_type IS NOT NULL"),
        "URLs carrying only gclid / fbclid / ttclid.", "Mapped to Google / Meta / TikTok by click id; otherwise paid revenue would fall into Direct.", "fix")
    add("Events", "Inconsistent utm_source spelling", one("SELECT COUNT(DISTINCT utm_source) FROM events WHERE utm_source IS NOT NULL"),
        "e.g. google/Google, fb/facebook/ig/instagram, tiktok/TikTok, klaviyo/newsletter.", "Lower-cased and mapped to 8 channels.", "fix")
    # purchase events vs orders
    test = one("SELECT COUNT(*) FROM events WHERE event_name='purchase' AND upper(order_id) LIKE 'TEST%'")
    add("Orders", "Test purchase events (TEST-*)", test, "Purchase pixel fired by QA with order ids like TEST-7.",
        "Ignored. Revenue comes only from the order system, which is the source of truth.", "exclude")
    rep = one("SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM events WHERE event_name='purchase' AND order_id NOT LIKE 'TEST%'")
    add("Orders", "Repeated purchase events", rep, "Same order fired the purchase pixel more than once (page refresh).",
        "Pixel purchases are never summed; they only link an order to a browser.", "fix")
    # orders
    orders_n = one("SELECT COUNT(*) FROM orders")
    add("Orders", "Webhook updates collapsed", one("SELECT COUNT(*) FROM order_webhooks") - orders_n,
        f"{one('SELECT COUNT(*) FROM order_webhooks')} webhooks describe {orders_n} orders; status changes (paid -> refunded / cancelled).",
        "Latest updated_at wins, independent of arrival order. Out-of-order older webhooks are ignored.", "fix")
    st = {r["financial_status"]: dict(r) for r in conn.execute(
        "SELECT financial_status, COUNT(*) AS n, SUM(total_inr) AS v FROM orders GROUP BY financial_status")}
    for s, verb in (("refunded", "refunded"), ("cancelled", "cancelled")):
        add("Orders", f"Orders later {verb}", st.get(s, {}).get("n", 0),
            f"Worth INR {round(st.get(s, {}).get('v') or 0):,} if they had stood.", "Excluded from revenue, ROAS and attributed orders.", "exclude")
    usd = one("SELECT COUNT(*) FROM orders WHERE currency='USD'")
    add("Orders", "Orders billed in USD", usd, f"Converted at {C.FX_TO_INR['USD']:g} INR/USD (the rate implied by the store's own price list).",
        "All revenue is reported in INR. Never summed in mixed currencies.", "fix")
    # journeys
    reasons = {r["reason"]: dict(r) for r in conn.execute(
        "SELECT a.reason, COUNT(*) AS n, SUM(o.total_inr) AS v FROM order_attribution a JOIN orders o USING (order_id) "
        "WHERE a.model = 'last_click' AND o.financial_status = 'paid' GROUP BY a.reason")}
    add("Journeys", "Paid orders with no linkable browser journey", reasons.get("no_journey", {}).get("n", 0),
        "Buyer email never seen on the site and no purchase pixel for that order (ad blockers / server-side orders).",
        "Reported honestly as 'Direct / Unattributed' instead of guessed.", "info")
    add("Journeys", f"Paid orders with no marketing touch in {C.ATTRIBUTION_WINDOW_DAYS} days", reasons.get("no_touch_in_window", {}).get("n", 0),
        "A known visitor, but only direct visits (or touches older than the lookback window).", "Credited to 'Direct / Unattributed'.", "info")
    multi = one("SELECT COUNT(*) FROM (SELECT person_id FROM person_map WHERE node LIKE 'a:%' GROUP BY person_id HAVING COUNT(*)>1)")
    add("Journeys", "People using more than one device", multi, "Devices stitched together through a shared email_hash / order.",
        "Treated as one person: touches on any device can earn credit; days-to-convert starts at the first visit on any device.", "fix")
    # spend
    rev = conn.execute("SELECT COUNT(*) AS n, SUM(l.spend - f.spend) AS d FROM ad_spend_current l JOIN "
                       "(SELECT DISTINCT ON (date, campaign) date, campaign, spend FROM ad_spend_pulls "
                       "ORDER BY date, campaign, pulled_at ASC) f USING (date, campaign) WHERE l.spend <> f.spend").fetchone()
    add("Ad spend", "Re-pulled spend rows (restated)", rev["n"], f"Platforms restated {rev['n']} day/campaign rows; net change INR {round(rev['d'] or 0):,}.",
        "Newest pull per (date, campaign) wins; older pulls are kept for audit.", "fix")
    zero = [r[0] for r in conn.execute(
        "SELECT s.campaign FROM (SELECT campaign FROM ad_spend_current GROUP BY campaign) s LEFT JOIN "
        "(SELECT campaign, COUNT(*) AS n FROM order_attribution a JOIN orders o USING (order_id) "
        "WHERE a.model = 'last_click' AND o.financial_status = 'paid' GROUP BY campaign) a "
        "USING (campaign) WHERE COALESCE(a.n, 0) = 0")]
    if zero:
        add("Ad spend", "Campaigns with spend but zero attributed orders", len(zero), ", ".join(zero),
            "Reported as ROAS 0.00 - flagged for review, not hidden.", "warn")
    return {"items": items, "events_total": ev_total}
