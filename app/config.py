"""Central, documented business rules. Every number the dashboard shows depends on these."""
import os
import pathlib


def _load_dotenv() -> None:
    """Tiny .env reader (KEY=VALUE lines). Real environment variables always win over the file."""
    f = pathlib.Path(__file__).resolve().parents[1] / ".env"
    if not f.is_file():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

# PostgreSQL connection string. Create the database first (see README), then point DATABASE_URL at it.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/urbanthread")
DB_POOL_MAX = int(os.getenv("UT_DB_POOL_MAX", "20"))

# Attribution lookback: a marketing touch can only get credit for an order placed within
# this many days AFTER the touch. 7 days = the common click-through window used by Meta
# (7-day click) and a sensible middle ground for a fashion store whose buyers mostly convert
# within days (see "Days to convert" in the dashboard). Overridable per request (?window_days=).
ATTRIBUTION_WINDOW_DAYS = int(os.getenv("UT_WINDOW_DAYS", "7"))

# created_at in the order system has 1s resolution; allow a touch up to 1s "after" the stored
# order time so a click in the same second as the order is not thrown away.
ORDER_TIME_TOLERANCE_MS = 999

# New session after this much inactivity (spec: 30 minutes).
SESSION_GAP_MS = 30 * 60 * 1000

# FX: orders.csv has 43 USD webhooks. Every USD price in the data is exactly the INR price / 84
# (1899 INR <-> 22.61 USD, 3999 <-> 47.61, 8998 <-> 107.12), so 84 is the store's own rate.
# Everything is reported in INR (the ad platforms bill in INR too).
FX_TO_INR = {"INR": 1.0, "USD": float(os.getenv("UT_USD_INR", "84"))}
REPORTING_CURRENCY = "INR"

# Device clocks are untrusted. If the device timestamp is more than 5 minutes in the future
# of the server receive time, or more than 7 days older, it is replaced by received_at.
# (Legit late arrivals in the data are <= 3 days: offline/batched pixels.)
TS_MAX_FUTURE_S = 5 * 60
TS_MAX_LATE_DAYS = 7

# Refresh worker: derived tables are rebuilt after ingest goes quiet for DEBOUNCE seconds,
# and at the latest every MAX_WAIT seconds while data keeps streaming in.
REFRESH_DEBOUNCE_S = float(os.getenv("UT_DEBOUNCE_S", "1.5"))
REFRESH_MAX_WAIT_S = float(os.getenv("UT_MAX_WAIT_S", "8"))

# Channel taxonomy
GOOGLE, META, TIKTOK = "Google Ads", "Meta Ads", "TikTok Ads"
EMAIL = "Email"
ORG_SEARCH, ORG_SOCIAL, REFERRAL = "Organic Search", "Organic Social", "Referral"
DIRECT = "Direct / Unattributed"
PAID_CHANNELS = [GOOGLE, META, TIKTOK]
PLATFORM_TO_CHANNEL = {"google": GOOGLE, "meta": META, "tiktok": TIKTOK}
CHANNEL_ORDER = [GOOGLE, META, TIKTOK, EMAIL, ORG_SEARCH, ORG_SOCIAL, REFERRAL, DIRECT]
