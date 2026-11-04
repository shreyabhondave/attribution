"""Behavioural tests for every rule that changes a number. Run:  python -m pytest -q"""
import itertools
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db, pipeline  # noqa: E402
from app import normalize as N
from app.main import app  # noqa: E402

T0 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
_ids = itertools.count(1)
UA = "Mozilla/5.0 (iPhone) Safari"
EMAIL = "e" * 64


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ev(anon, name, at, url="https://www.urbanthread.in/", ref="", **kw):
    return {"event_id": f"ev{next(_ids)}", "event_name": name, "ts": iso(at), "received_at": iso(at + timedelta(seconds=1)),
            "anonymous_id": anon, "page_url": url, "referrer": ref, "user_agent": UA, "ip": "1.1.1.1", **kw}


def order(oid, at, status="paid", total=1000, cur="INR", email=EMAIL, updated=None):
    return {"order_id": oid, "email_hash": email, "created_at": at.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": (updated or at).strftime("%Y-%m-%d %H:%M:%S"), "total": str(total), "currency": cur,
            "financial_status": status}


GADS = "https://www.urbanthread.in/?utm_source=google&utm_medium=cpc&utm_campaign=g_search_brand&gclid=x"
META = "https://www.urbanthread.in/?utm_source=Facebook&utm_medium=paid_social&utm_campaign=meta_retargeting_sep&fbclid=y"


TEST_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture()
def client():
    """A TestClient on an EMPTY PostgreSQL database. The tests TRUNCATE every table, so this refuses to run
    unless TEST_DATABASE_URL is set explicitly and names a database containing 'test'."""
    if not TEST_URL:
        pytest.skip("set TEST_DATABASE_URL to a throwaway PostgreSQL database (name must contain 'test')")
    dbname = conninfo_to_dict(TEST_URL).get("dbname", "")
    if "test" not in dbname:
        pytest.skip(f"refusing to run destructive tests on database '{dbname}' (name must contain 'test')")
    db.configure(TEST_URL)
    try:
        db.init()
    except Exception as e:  # noqa: BLE001  - any connection problem means "no database", not "test failure"
        pytest.skip(f"PostgreSQL not reachable: {e}")
    db.reset()
    with TestClient(app) as c:
        yield c
    db.close()


def push(c, events=(), orders=(), spend=()):
    for e in events:
        assert c.post("/collect", json=e).status_code == 202
    for o in orders:
        assert c.post("/webhooks/orders", json=o).status_code == 202
    for s in spend:
        assert c.post("/ad-spend", json=s).status_code == 202
    pipeline.refresh()


def rep(c, **q):
    q.setdefault("from", "2026-09-01")
    q.setdefault("to", "2026-09-30")
    return c.get("/api/report", params=q).json()


def row(r, channel):
    return next((x for x in r["rows"] if x["channel"] == channel), None)


def n_orders(r, channel):
    x = row(r, channel)
    return x["orders"] if x else 0


def journey(a="A", email=EMAIL):
    """Google touch, then Meta touch a day later, then a direct visit, then identify."""
    return [ev(a, "page_view", T0, GADS, "https://www.google.com/"),
            ev(a, "page_view", T0 + timedelta(days=1), META, "https://l.facebook.com/"),
            ev(a, "page_view", T0 + timedelta(days=2), ref="https://www.urbanthread.in/cart"),
            ev(a, "identify", T0 + timedelta(days=2, minutes=1), email_hash=email)]


# ---------------------------------------------------------------- normalisation
def test_timestamp_formats():
    a = N.parse_ts("2026-09-01T06:06:52.114+05:30")
    assert a == datetime(2026, 9, 1, 0, 36, 52, 114000, tzinfo=UTC)
    assert N.parse_ts(1788229809262) == datetime.fromtimestamp(1788229809.262, UTC)
    assert N.parse_ts("2026-09-01 01:07:01") == datetime(2026, 9, 1, 1, 7, 1, tzinfo=UTC)
    assert N.parse_ts("garbage") is None


def test_impossible_device_clock_falls_back_to_received():
    recv = datetime(2026, 9, 5, tzinfo=UTC)
    assert N.effective_ts(datetime(2036, 9, 24, tzinfo=UTC), recv)[1] == "received_future"
    assert N.effective_ts(datetime(2025, 7, 28, tzinfo=UTC), recv)[1] == "received_stale"
    assert N.effective_ts(recv - timedelta(days=2), recv)[1] == "device"  # legit late arrival is kept


@pytest.mark.parametrize("url,ref,channel", [
    ("https://x/?utm_source=Google&utm_medium=CPC&utm_campaign=A", "", "Google Ads"),
    ("https://x/?utm_source=ig&utm_medium=Paid_Social", "", "Meta Ads"),
    ("https://x/?fbclid=abc", "https://l.facebook.com/", "Meta Ads"),       # click id, no utm
    ("https://x/?gclid=abc", "", "Google Ads"),
    ("https://x/?ttclid=abc", "", "TikTok Ads"),
    ("https://x/?utm_source=newsletter&utm_medium=email", "", "Email"),
    ("https://x/", "https://www.google.com/", "Organic Search"),
    ("https://x/", "https://l.facebook.com/", "Organic Social"),
    ("https://x/", "https://www.urbanthread.in/cart", "Direct / Unattributed"),
    ("https://x/", "", "Direct / Unattributed"),
])
def test_channel_classification(url, ref, channel):
    assert N.classify(url, ref)["channel"] == channel


# ---------------------------------------------------------------- attribution
def test_last_vs_first_click_and_direct_never_steals_credit(client):
    push(client, journey(), [order("#1", T0 + timedelta(days=2, minutes=5))])
    assert row(rep(client), "Meta Ads")["revenue"] == 1000       # last NON-direct touch
    assert row(rep(client, model="first_click"), "Google Ads")["revenue"] == 1000
    assert n_orders(rep(client), "Direct / Unattributed") == 0


def test_lookback_window_boundary(client):
    push(client, [ev("A", "page_view", T0, GADS), ev("A", "identify", T0 + timedelta(minutes=1), email_hash=EMAIL)],
         [order("#1", T0 + timedelta(days=8))])
    assert row(rep(client), "Direct / Unattributed")["revenue"] == 1000      # 8d > 7d window
    assert row(rep(client, window_days=14), "Google Ads")["revenue"] == 1000  # on-demand wider window
    assert row(rep(client, window_days=7), "Direct / Unattributed")["orders"] == 1


def test_touch_after_order_gets_no_credit(client):
    push(client, [ev("A", "identify", T0, email_hash=EMAIL), ev("A", "page_view", T0 + timedelta(hours=3), GADS)],
         [order("#1", T0 + timedelta(hours=1))])
    assert n_orders(rep(client), "Google Ads") == 0


def test_cross_device_touches_count(client):
    # ad click on the PHONE (device A), buyer logs in on the LAPTOP (device B) where the order happens
    push(client, [ev("A", "page_view", T0, GADS), ev("A", "identify", T0 + timedelta(minutes=1), email_hash=EMAIL),
                  ev("B", "identify", T0 + timedelta(days=1), email_hash=EMAIL),
                  ev("B", "purchase", T0 + timedelta(days=1, minutes=3), order_id="#1", email_hash=EMAIL, value=1000, currency="INR")],
         [order("#1", T0 + timedelta(days=1, minutes=3))])
    assert row(rep(client), "Google Ads")["orders"] == 1
    d = client.get("/api/orders/%231").json()
    assert len(d["devices"]) == 2 and d["attribution"]["last_click"]["reason"] == "touch"


def test_order_linked_by_purchase_pixel_when_email_unseen(client):
    push(client, [ev("A", "page_view", T0, GADS),
                  ev("A", "purchase", T0 + timedelta(hours=1), order_id="#1", value=1000, currency="INR")],
         [order("#1", T0 + timedelta(hours=1), email="f" * 64)])
    assert row(rep(client), "Google Ads")["orders"] == 1


def test_unlinkable_order_is_direct_not_guessed(client):
    push(client, [ev("A", "page_view", T0, GADS)], [order("#1", T0 + timedelta(hours=1), email="9" * 64)])
    r = row(rep(client), "Direct / Unattributed")
    assert r["orders"] == 1
    assert client.get("/api/orders/%231").json()["attribution"]["last_click"]["reason"] == "no_journey"


def test_late_event_rewrites_the_past(client):
    push(client, [ev("A", "identify", T0, email_hash=EMAIL)], [order("#1", T0 + timedelta(days=1))])
    assert row(rep(client), "Direct / Unattributed")["revenue"] == 1000
    late = ev("A", "page_view", T0 + timedelta(hours=2), GADS)       # arrives days later, device time is earlier
    late["received_at"] = iso(T0 + timedelta(days=3))
    push(client, [late])
    r = rep(client)
    assert row(r, "Google Ads")["revenue"] == 1000 and n_orders(r, "Direct / Unattributed") == 0


# ---------------------------------------------------------------- ingestion hygiene
def test_duplicate_events_are_idempotent(client):
    e = ev("A", "page_view", T0, GADS)
    for _ in range(3):
        client.post("/collect", json=e)
    pipeline.refresh()
    assert client.get("/api/status").json()["events_stored"] == 1
    assert client.get("/api/status").json()["counters"]["events_duplicate"] == 2


def test_bots_never_count(client):
    bot = ev("BOT", "page_view", T0, GADS)
    bot["user_agent"] = "Mozilla/5.0 HeadlessChrome/129.0"
    push(client, [bot, ev("A", "page_view", T0 + timedelta(minutes=1), "https://www.urbanthread.in/")])
    assert client.get("/api/status").json()["sessions"] == 1


def test_webhooks_out_of_order_and_refund(client):
    paid = order("#1", T0, "paid")
    refunded = order("#1", T0, "refunded", updated=T0 + timedelta(days=2))
    push(client, [ev("A", "page_view", T0 - timedelta(hours=1), GADS), ev("A", "identify", T0 - timedelta(minutes=50), email_hash=EMAIL)],
         [paid])
    assert row(rep(client), "Google Ads")["revenue"] == 1000
    push(client, orders=[refunded])
    r = rep(client)
    assert row(r, "Google Ads")["revenue"] == 0 and row(r, "Google Ads")["refunded_orders"] == 1
    # the OLD 'paid' webhook is re-delivered after the refund: must not resurrect the revenue
    client.post("/webhooks/orders", json=paid)
    pipeline.refresh()
    assert row(rep(client), "Google Ads")["revenue"] == 0
    assert client.get("/api/status").json()["counters"]["webhooks_duplicate"] == 1


def test_stale_webhook_arriving_first_does_not_win(client):
    client.post("/webhooks/orders", json=order("#1", T0, "refunded", updated=T0 + timedelta(days=2)))
    client.post("/webhooks/orders", json=order("#1", T0, "paid"))     # older updated_at arrives later
    assert client.get("/api/status").json()["counters"]["webhooks_stale"] == 1
    pipeline.refresh()
    assert client.get("/api/orders", params={"from": "2026-09-01", "to": "2026-09-30"}).json()["rows"][0]["status"] == "refunded"


def test_usd_is_converted_and_test_orders_ignored(client):
    push(client, [ev("A", "page_view", T0 - timedelta(hours=1), GADS), ev("A", "identify", T0 - timedelta(minutes=5), email_hash=EMAIL)],
         [order("#1", T0, total=22.61, cur="USD"), order("TEST-1", T0)])
    r = rep(client)
    assert r["totals"]["orders"] == 1 and abs(r["totals"]["revenue"] - 22.61 * 84) < 0.01


def test_ad_spend_restatement_newest_pull_wins(client):
    base = {"date": "2026-09-02", "platform": "meta", "campaign": "meta_prospecting_sep", "currency": "INR"}
    push(client, spend=[{**base, "spend": "3385.32", "pulled_at": "2026-09-02 23:29:00"},
                        {**base, "spend": "3845.26", "pulled_at": "2026-09-04 06:00:00"},
                        {**base, "spend": "3385.32", "pulled_at": "2026-09-02 23:29:00"}])   # replay
    assert row(rep(client), "Meta Ads")["spend"] == 3845.26


def test_sessions_split_after_30_minutes():
    evs = [{"event_id": str(i), "event_name": "page_view", "ts_ms": t * 60_000, "ts_utc": "2026-09-01T00:00:00.000Z",
            "page_url": "u", "channel": "Direct / Unattributed", "utm_campaign": None, "is_touch": 0, "order_id": None}
           for i, t in enumerate([0, 29, 60, 61])]      # gap 29 -> same session; gap 31 -> new session
    s = pipeline.build_sessions("a", evs)
    assert [x["n_events"] for x in s] == [2, 2]


def test_rejects_garbage(client):
    assert client.post("/collect", json={"nope": 1}).status_code == 422
    assert client.post("/webhooks/orders", json={"order_id": "#1"}).status_code == 422
    assert client.get("/api/report", params={"from": "bad"}).status_code == 400
