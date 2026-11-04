-- =====================================================================================
-- queries.sql  -  PostgreSQL, written against this project's own tables and run as-is:
--
--     psql "$DATABASE_URL" -f queries.sql
--
-- Tables used (schema in app/db.py):
--   events(event_id PK, event_name, anonymous_id, email_hash, ts_utc TIMESTAMPTZ, order_id, is_bot BOOLEAN, ...)
--       - already de-duplicated on event_id
--       - ts_utc = effective event time: device time, or server received_at when the device
--         clock was impossible (see README "Data decisions")
--       - is_bot = true for crawlers / headless browsers (excluded below)
--   orders(order_id PK, email_hash, created_at TIMESTAMPTZ, financial_status, total_inr, ...)
--       - one row per order = the LATEST webhook (financial_status is the current status)
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- Q1. Sessions: split each visitor's events into sessions (a new session starts after
--     more than 30 minutes of inactivity). Return session count and median session
--     length per day.
--
-- "Visitor" = anonymous_id (the browser cookie), "session length" = last event minus first
-- event of the session. A one-event session therefore has length 0 and is still counted.
-- A session belongs to the UTC day it STARTED on. Bots are excluded.
-- -------------------------------------------------------------------------------------
WITH ev AS (
    SELECT anonymous_id, event_id, ts_utc AS ts
    FROM   events
    WHERE  NOT is_bot
),
flagged AS (                      -- 1 on the first event of a visitor and after a >30 min gap
    SELECT anonymous_id, event_id, ts,
           CASE WHEN LAG(ts) OVER w IS NULL
                  OR ts - LAG(ts) OVER w > INTERVAL '30 minutes'
                THEN 1 ELSE 0 END AS is_new_session
    FROM   ev
    WINDOW w AS (PARTITION BY anonymous_id ORDER BY ts, event_id)
),
numbered AS (                     -- running total of the flags = session number per visitor
    SELECT anonymous_id, ts,
           SUM(is_new_session) OVER (PARTITION BY anonymous_id ORDER BY ts, event_id
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_no
    FROM   flagged
),
sessions AS (
    SELECT anonymous_id, session_no,
           MIN(ts) AS started_at,
           MAX(ts) AS ended_at
    FROM   numbered
    GROUP  BY anonymous_id, session_no
)
SELECT (started_at AT TIME ZONE 'UTC')::date                                   AS day,
       COUNT(*)                                                                AS sessions,
       percentile_cont(0.5) WITHIN GROUP
           (ORDER BY EXTRACT(EPOCH FROM (ended_at - started_at)))              AS median_session_seconds
FROM   sessions
GROUP  BY 1
ORDER  BY 1;


-- -------------------------------------------------------------------------------------
-- Q2. Days to convert: for each paid order, the number of days between that buyer's very
--     first visit (on ANY of their devices) and the order.
--
-- A buyer's devices = every anonymous_id that was ever seen with the buyer's email_hash, plus
-- the browser that fired the purchase pixel for the order. The first visit is the earliest
-- non-bot event on any of those devices. "Paid" = latest webhook status is 'paid'
-- (refunded / cancelled orders are not paid). Orders whose buyer can't be linked to any
-- browser (email never seen on site, no purchase pixel) return NULL instead of a guess.
-- Both a calendar-day difference and the exact fractional days are returned.
-- -------------------------------------------------------------------------------------
WITH buyer_devices AS (
    SELECT DISTINCT email_hash, anonymous_id
    FROM   events
    WHERE  email_hash IS NOT NULL AND NOT is_bot
    UNION
    SELECT o.email_hash, e.anonymous_id          -- device that fired the purchase pixel
    FROM   events e
    JOIN   orders o ON o.order_id = e.order_id
    WHERE  e.event_name = 'purchase' AND NOT e.is_bot AND o.email_hash IS NOT NULL
),
first_visit AS (
    SELECT d.email_hash, MIN(e.ts_utc) AS first_visit_at
    FROM   buyer_devices d
    JOIN   events e ON e.anonymous_id = d.anonymous_id AND NOT e.is_bot
    GROUP  BY d.email_hash
)
SELECT o.order_id,
       o.created_at                                                                      AS ordered_at,
       f.first_visit_at,
       GREATEST(0, (o.created_at AT TIME ZONE 'UTC')::date
                 - (f.first_visit_at AT TIME ZONE 'UTC')::date)                          AS days_to_convert,
       GREATEST(0, ROUND((EXTRACT(EPOCH FROM (o.created_at - f.first_visit_at))
                          / 86400.0)::numeric, 2))                                       AS days_to_convert_exact
FROM   orders o
LEFT   JOIN first_visit f ON f.email_hash = o.email_hash
WHERE  o.financial_status = 'paid'
ORDER  BY o.created_at;
