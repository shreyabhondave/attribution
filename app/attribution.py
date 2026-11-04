"""Attribution engine: pure functions over in-memory inputs, so refresh() and the reporting API
share one implementation (and a non-default lookback window can be evaluated on demand).

Models
  last_click  - the LAST marketing touch inside the lookback window before the order gets 100%.
  first_click - the FIRST marketing touch inside the window gets 100%.

A "touch" is a human page_view that carries a marketing signal (utm / click id / external
referrer). Direct visits and on-site navigation are NOT touches, so a buyer who returns
directly still credits the ad that brought them (standard last-NON-DIRECT click).
Touches from ALL of a person's devices count (people are linked via email_hash / order_id).
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

from . import config as C

MODELS = ("last_click", "first_click")


def attribute(orders: list[dict], touches_by_person: dict[str, list[tuple]], order_person: dict[str, str | None],
              journey_persons: set[str], window_days: int, model: str) -> list[dict]:
    """orders: [{order_id, created_ms}], touches_by_person: person -> [(ts_ms, event_id, channel, campaign)]
    sorted ascending. Returns one row per order."""
    window_ms = int(window_days * 86_400_000)
    ts_index = {p: [t[0] for t in ts] for p, ts in touches_by_person.items()}
    out = []
    for o in orders:
        oid, t = o["order_id"], o["created_ms"]
        person = order_person.get(oid)
        row = {"order_id": oid, "model": model, "channel": C.DIRECT, "campaign": None, "touch_event_id": None,
               "touch_ms": None, "days_to_order": None, "person_id": person, "n_touches": 0,
               "reason": "no_journey", "window_days": window_days}
        if person is not None and person in journey_persons:
            row["reason"] = "no_touch_in_window"
            touches = touches_by_person.get(person)
            if touches:
                ts = ts_index[person]
                lo = bisect_left(ts, t - window_ms)
                hi = bisect_right(ts, t + C.ORDER_TIME_TOLERANCE_MS)
                if hi > lo:
                    pick = touches[hi - 1] if model == "last_click" else touches[lo]
                    row.update(channel=pick[2], campaign=pick[3], touch_event_id=pick[1], touch_ms=pick[0],
                               days_to_order=round(max(t - pick[0], 0) / 86_400_000, 3), n_touches=hi - lo,
                               reason="touch")
        out.append(row)
    return out


def load_touches(conn, anon_to_person: dict[str, str]):
    """Touches grouped per person, ascending in time (ties broken by event_id => deterministic)."""
    by: dict[str, list[tuple]] = {}
    for r in conn.execute("SELECT event_id, anonymous_id, ts_ms, channel, utm_campaign FROM events "
                          "WHERE is_touch AND NOT is_bot ORDER BY ts_ms, event_id"):
        p = anon_to_person.get(r["anonymous_id"])
        if p is not None:
            by.setdefault(p, []).append((r["ts_ms"], r["event_id"], r["channel"], r["utm_campaign"]))
    return by


def attribution_for_window(conn, window_days: int, model: str) -> list[dict]:
    """Recompute from stored person_map (used by the API for non-default windows)."""
    anon_to_person = {r["node"][2:]: r["person_id"] for r in conn.execute(
        "SELECT node, person_id FROM person_map WHERE node LIKE 'a:%'")}
    journey = set(anon_to_person.values())
    order_person = {r["order_id"]: r["person_id"] for r in conn.execute(
        "SELECT order_id, person_id FROM order_attribution WHERE model='last_click'")}
    orders = [dict(r) for r in conn.execute("SELECT order_id, created_ms FROM orders")]
    return attribute(orders, load_touches(conn, anon_to_person), order_person, journey, window_days, model)
