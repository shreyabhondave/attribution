"""FastAPI app: ingestion + reporting API + static dashboard.   Run:  uvicorn app.main:app --port 8000"""
from __future__ import annotations

import logging
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as C
from . import db, ingest, pipeline
from . import reports as R

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
STATIC = pathlib.Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    pipeline.start()
    yield
    pipeline.stop()
    db.close()


app = FastAPI(title="Urban Thread first-party attribution", version="1.0", lifespan=lifespan)
app.include_router(ingest.router)


def _params(frm, to, conn):
    try:
        frm, to = R.valid_date(frm), R.valid_date(to)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if not frm or not to:
        s = R.status(conn)
        frm, to = frm or s["data_from"], to or s["data_to"]
    if not frm or not to:
        raise HTTPException(404, "no data ingested yet")
    if frm > to:
        raise HTTPException(400, "'from' must be <= 'to'")
    return frm, to


def _run(fn, frm, to, *args, needs_model=True, model="last_click", window_days=None, **kw):
    with db.read() as conn:
        frm, to = _params(frm, to, conn)
        w = window_days or C.ATTRIBUTION_WINDOW_DAYS
        if not 1 <= w <= 365:
            raise HTTPException(400, "window_days must be 1..365")
        try:
            return fn(conn, frm, to, model, w, *args, **kw) if needs_model else fn(conn, frm, to)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None


Q = dict(frm=Query(None, alias="from", description="YYYY-MM-DD (UTC), default = first data day"),
         to=Query(None, description="YYYY-MM-DD (UTC), default = last data day"))
MODEL = Query("last_click", pattern="^(last_click|first_click)$")
WIN = Query(None, ge=1, le=365, description="attribution lookback in days (default 7)")


@app.get("/api/report", summary="Orders, revenue, ad spend and ROAS per channel for a date range")
def report(frm=Q["frm"], to=Q["to"], model: str = MODEL, window_days: int | None = WIN):
    return _run(R.channels, frm, to, model=model, window_days=window_days)


@app.get("/api/daily", summary="Same metrics per day (and per channel per day)")
def daily(frm=Q["frm"], to=Q["to"], model: str = MODEL, window_days: int | None = WIN):
    return _run(R.daily, frm, to, model=model, window_days=window_days)


@app.get("/api/campaigns", summary="Spend and attributed revenue per campaign")
def campaigns(frm=Q["frm"], to=Q["to"], model: str = MODEL, window_days: int | None = WIN):
    return _run(R.campaigns, frm, to, model=model, window_days=window_days)


@app.get("/api/funnel", summary="Sessions -> add to cart -> checkout -> purchase, plus daily sessions")
def funnel(frm=Q["frm"], to=Q["to"]):
    return _run(R.funnel, frm, to, needs_model=False)


@app.get("/api/conversion-lag", summary="Days between a buyer's first visit (any device) and a paid order")
def conversion_lag(frm=Q["frm"], to=Q["to"]):
    return _run(R.conversion_lag, frm, to, needs_model=False)


@app.get("/api/orders", summary="Order explorer: every order with its credited channel")
def orders(frm=Q["frm"], to=Q["to"], model: str = MODEL, window_days: int | None = WIN, channel: str | None = None,
           status: str | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return _run(R.order_list, frm, to, channel, status, q, limit, offset, model=model, window_days=window_days)


@app.get("/api/orders/{order_id:path}", summary="Explain one order: devices, touches, and why it got its channel")
def order_detail(order_id: str, window_days: int | None = WIN):
    with db.read() as conn:
        out = R.order_explain(conn, order_id, window_days or C.ATTRIBUTION_WINDOW_DAYS)
    if out is None:
        raise HTTPException(404, "unknown order")
    return out


@app.get("/api/quality", summary="Everything excluded or corrected, with counts")
def quality():
    with db.read() as conn:
        return R.quality(conn)


@app.get("/api/status", summary="Ingest / pipeline health and available date range")
def status():
    with db.read() as conn:
        return R.status(conn)


@app.post("/admin/refresh", summary="Rebuild derived tables now (full=true rebuilds every session)")
def admin_refresh(full: bool = False):
    return pipeline.refresh(full=full)


@app.post("/admin/reset", summary="Wipe all data (demo / tests)")
def admin_reset():
    db.reset()
    return {"ok": True}


@app.get("/", include_in_schema=False)
def index():
    """The React dashboard (built by `npm run build` in frontend/ into app/static/app)."""
    page = STATIC / "app" / "index.html"
    if not page.exists():
        raise HTTPException(503, "Dashboard not built. Run `npm install && npm run build` in frontend/ (the API still works).")
    return FileResponse(page)


app.mount("/static", StaticFiles(directory=STATIC), name="static")
