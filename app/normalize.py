"""Pure functions that clean one raw record. No I/O, so they are trivial to unit-test."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from . import config as C

_NUM = re.compile(r"^-?\d+(\.\d+)?$")
_BOT = re.compile(r"bot|crawl|spider|headless|python-requests|curl/|wget|scrapy|phantom|lighthouse|ahrefs|semrush",
                  re.I)


def parse_ts(v) -> datetime | None:
    """Accepts ISO-8601 with Z / +05:30 / naive (=UTC), 'YYYY-MM-DD HH:MM:SS', epoch ms or s."""
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and _NUM.match(v.strip())):
            n = float(v)
            if abs(n) > 1e11:  # milliseconds
                n /= 1000.0
            return datetime.fromtimestamp(n, UTC)
        s = str(v).strip()
        if not s:
            return None
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (ValueError, OverflowError, OSError):
        return None


def ts_format(v) -> str:
    if isinstance(v, (int, float)):
        return "epoch"
    s = str(v)
    if s.endswith("Z"):
        return "iso_z"
    if re.search(r"[+-]\d\d:?\d\d$", s):
        return "iso_offset"
    return "naive_utc"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def to_ms(dt: datetime) -> int:
    return int(round(dt.timestamp() * 1000))


def effective_ts(ts: datetime | None, received: datetime) -> tuple[datetime, str]:
    """Device time when it is believable, otherwise the server's receive time."""
    if ts is None:
        return received, "received_missing"
    delta = (received - ts).total_seconds()
    if delta < -C.TS_MAX_FUTURE_S:
        return received, "received_future"
    if delta > C.TS_MAX_LATE_DAYS * 86400:
        return received, "received_stale"
    return ts, "device"


def is_bot(user_agent: str | None) -> bool:
    return bool(user_agent and _BOT.search(user_agent))


# ---------------------------------------------------------------- channel classification
_SEARCH = ("google.", "bing.", "duckduckgo.", "yahoo.", "ecosia.", "brave.com", "baidu.", "yandex.")
_SOCIAL = ("facebook.", "instagram.", "tiktok.", "pinterest.", "twitter.", "t.co", "x.com", "youtube.",
           "linkedin.", "reddit.", "snapchat.")
_INTERNAL = ("urbanthread.in",)


def _host(url: str | None) -> str:
    if not url:
        return ""
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _first(q: dict, k: str) -> str:
    v = q.get(k)
    return v[0].strip() if v and v[0] else ""


def classify(page_url: str | None, referrer: str | None) -> dict:
    """Map a page view to a marketing channel.

    Priority: utm_source (normalised) -> platform click id (gclid/fbclid/ttclid) -> referrer host.
    Click ids matter: ~500 landing URLs carry gclid/fbclid/ttclid and NO utm tags; dropping them
    would silently move paid revenue into 'Direct'. `is_touch` is False when there is no marketing
    signal (direct visit or on-site navigation) - those never receive credit.
    """
    q = parse_qs(urlparse(page_url or "").query)
    src = _first(q, "utm_source").lower()
    med = _first(q, "utm_medium").lower()
    camp = _first(q, "utm_campaign").lower() or None
    click = ("gclid" if _first(q, "gclid") else "fbclid" if _first(q, "fbclid") else
             "ttclid" if _first(q, "ttclid") else None)

    channel = None
    if src or med:
        if med == "email" or src in {"klaviyo", "newsletter", "email", "mailchimp"}:
            channel = C.EMAIL
        elif src in {"google", "adwords", "google_ads", "googleads"}:
            channel = C.ORG_SEARCH if med in {"organic", "seo"} else C.GOOGLE
        elif src in {"fb", "facebook", "ig", "instagram", "meta", "facebook_ads"}:
            channel = C.META
        elif src in {"tiktok", "tt", "tiktok_ads"}:
            channel = C.TIKTOK
        elif src:
            channel = C.REFERRAL
    if channel is None and click:
        channel = {"gclid": C.GOOGLE, "fbclid": C.META, "ttclid": C.TIKTOK}[click]
    if channel is None:
        h = _host(referrer)
        if not h or any(h == d or h.endswith("." + d) for d in _INTERNAL):
            channel = C.DIRECT
        elif any(s in h for s in _SEARCH):
            channel = C.ORG_SEARCH
        elif any(s in h for s in _SOCIAL):
            channel = C.ORG_SOCIAL
        else:
            channel = C.REFERRAL
    return {
        "channel": channel,
        "is_touch": channel != C.DIRECT,
        "utm_source": src or None,
        "utm_medium": med or None,
        "utm_campaign": camp,
        "click_id_type": click,
    }
