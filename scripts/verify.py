"""Independent re-computation of the headline numbers straight from the RAW FILES with pandas
(different code path from the service: no SQLite, no app.* imports) and a diff against the API.

    python scripts/verify.py [--url http://127.0.0.1:8000] [--data-dir .] [--from 2026-09-01 --to 2026-09-30]

If every line says OK, the service's per-channel orders / revenue / spend agree with a from-scratch
calculation, which is the evidence behind "numbers you can defend".
"""
import argparse
import json
import sys
import urllib.request
from urllib.parse import parse_qs, urlparse

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8000")
ap.add_argument("--data-dir", default=".")
ap.add_argument("--from", dest="frm", default=None)
ap.add_argument("--to", default=None)
ap.add_argument("--window", type=int, default=7)
a = ap.parse_args()

ev = pd.read_json(f"{a.data_dir}/events.jsonl", lines=True, dtype=False, convert_dates=False)
orders = pd.read_csv(f"{a.data_dir}/orders.csv", dtype={"order_id": str})
spend = pd.read_csv(f"{a.data_dir}/ad_spend.csv")

# ---- events: dedupe, fix clocks, drop bots
ev = ev.drop_duplicates("event_id", keep="first")


def to_utc(v):
    if isinstance(v, (int, float)) and not pd.isna(v):
        return pd.to_datetime(int(v), unit="ms", utc=True)
    return pd.to_datetime(v, utc=True, format="ISO8601")


ev["ts_dt"] = ev["ts"].map(to_utc)
ev["rx_dt"] = ev["received_at"].map(to_utc)
lag = (ev["rx_dt"] - ev["ts_dt"]).dt.total_seconds()
ev["t"] = ev["ts_dt"].where((lag >= -300) & (lag <= 7 * 86400), ev["rx_dt"])
bot = ev["user_agent"].str.contains("Headless|python-requests|Ahrefs", case=False, regex=True)
ev = ev[~bot].sort_values(["t", "event_id"])


def channel(row):
    q = parse_qs(urlparse(row.page_url).query)
    def g(k):
        return (q.get(k) or [""])[0].lower()

    src, med = g("utm_source"), g("utm_medium")
    if src in ("klaviyo", "newsletter") or med == "email":
        return "Email"
    if src == "google":
        return "Google Ads"
    if src in ("fb", "facebook", "ig", "instagram"):
        return "Meta Ads"
    if src == "tiktok":
        return "TikTok Ads"
    if g("gclid"):
        return "Google Ads"
    if g("fbclid"):
        return "Meta Ads"
    if g("ttclid"):
        return "TikTok Ads"
    host = urlparse(row.referrer or "").netloc.replace("www.", "")
    if not host or host.endswith("urbanthread.in"):
        return None
    if any(s in host for s in ("google.", "bing.", "duckduckgo.")):
        return "Organic Search"
    if any(s in host for s in ("facebook.", "tiktok.", "instagram.")):
        return "Organic Social"
    return "Referral"


pv = ev[ev.event_name == "page_view"].copy()
pv["ch"] = [channel(r) for r in pv.itertuples()]
touches = pv[pv.ch.notna()]

# ---- people: email if the browser ever identified, else the browser itself
anon_email = ev.dropna(subset=["email_hash"]).drop_duplicates("anonymous_id").set_index("anonymous_id")["email_hash"]
person_of_anon = {x: anon_email.get(x, "anon:" + x) for x in ev.anonymous_id.unique()}
touches = touches.assign(person=touches.anonymous_id.map(person_of_anon))
purch = ev[(ev.event_name == "purchase")].drop_duplicates("order_id").set_index("order_id")["anonymous_id"]

# ---- orders: latest webhook wins
orders["u"] = pd.to_datetime(orders.updated_at, utc=True)
orders["c"] = pd.to_datetime(orders.created_at, utc=True)
cur = orders.sort_values("u").groupby("order_id").tail(1).copy()
cur["inr"] = cur.total * cur.currency.map({"INR": 1, "USD": 84})
cur["day"] = cur.c.dt.strftime("%Y-%m-%d")

by_person = {p: g.sort_values("t") for p, g in touches.groupby("person")}
win = pd.Timedelta(days=a.window)
credited = []
for o in cur.itertuples():
    person = o.email_hash if o.email_hash in set(person_of_anon.values()) else (
        person_of_anon.get(purch.get(o.order_id)) if o.order_id in purch.index else None)
    ch = "Direct / Unattributed"
    if person in by_person:
        g = by_person[person]
        g = g[(g.t <= o.c + pd.Timedelta(milliseconds=999)) & (g.t >= o.c - win)]
        if len(g):
            ch = g.iloc[-1].ch
    credited.append(ch)
cur["ch"] = credited

frm, to = a.frm or cur.day.min(), a.to or cur.day.max()
paid = cur[(cur.financial_status == "paid") & cur.day.between(frm, to)]
mine = paid.groupby("ch").agg(orders=("inr", "size"), revenue=("inr", "sum"))

sp = spend.sort_values("pulled_at").groupby(["date", "campaign"]).tail(1)
sp = sp[sp.date.between(frm, to)]
mine_spend = sp.groupby("platform").spend.sum().rename({"google": "Google Ads", "meta": "Meta Ads", "tiktok": "TikTok Ads"})

api = json.load(urllib.request.urlopen(f"{a.url}/api/report?from={frm}&to={to}&window_days={a.window}"))
bad = 0
print(f"{'channel':24}{'orders (api/indep)':>22}{'revenue (api/indep)':>34}{'spend (api/indep)':>34}")
for r in api["rows"]:
    c = r["channel"]
    o2 = int(mine.orders.get(c, 0))
    r2 = round(float(mine.revenue.get(c, 0)), 2)
    s2 = round(float(mine_spend.get(c, 0)), 2)
    ok = r["orders"] == o2 and abs(r["revenue"] - r2) < 0.05 and abs(r["spend"] - s2) < 0.05
    bad += not ok
    print(f"{c:24}{r['orders']:>10}/{o2:<10}{r['revenue']:>16,.2f}/{r2:<16,.2f}{r['spend']:>16,.2f}/{s2:<16,.2f}  {'OK' if ok else 'MISMATCH'}")
tot_ok = api["totals"]["orders"] == len(paid) and abs(api["totals"]["revenue"] - paid.inr.sum()) < 0.05
print(f"{'TOTAL':24}{api['totals']['orders']:>10}/{len(paid):<10}{api['totals']['revenue']:>16,.2f}/{paid.inr.sum():<16,.2f}  {'OK' if tot_ok else 'MISMATCH'}")
sys.exit(1 if bad or not tot_ok else 0)
