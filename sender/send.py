#!/usr/bin/env python
"""Replay the Urban Thread files into a RUNNING service over HTTP, like live traffic.

    python sender/send.py                              # September files in the repo root
    python sender/send.py --data-dir ../oct_data       # the 1-3 October drop (same file names)
    python sender/send.py --only orders --concurrency 20

What it does
  * events.jsonl  -> POST /collect            (one event per request, like a tracking pixel)
  * orders.csv    -> POST /webhooks/orders    (one webhook per request)
  * ad_spend.csv  -> POST /ad-spend
  * Each file is read in FILE ORDER. With --mode interleave (default) the three files are merged by
    their own clock (received_at / updated_at / pulled_at) so spend, orders and events arrive
    together as they would live; --mode sequential sends one file after another.
  * --concurrency N (default 15) worker threads, each with a persistent keep-alive connection.
    Requests are handed out, and therefore started, in file order.
  * Connection errors / 5xx are retried with backoff. The endpoints are idempotent, so a retry or
    a complete re-run can never double count.
It speaks only HTTP; nothing touches the database directly. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import heapq
import http.client
import json
import pathlib
import queue
import sys
import threading
import time
from collections import Counter
from urllib.parse import urlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.normalize import parse_ts  # noqa: E402  (only used to order the merged stream)

FILES = {  # kind -> (filename, endpoint, clock field)
    "events": ("events.jsonl", "/collect", "received_at"),
    "orders": ("orders.csv", "/webhooks/orders", "updated_at"),
    "spend": ("ad_spend.csv", "/ad-spend", "pulled_at"),
}


def read_file(path: pathlib.Path):
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
    else:
        with path.open(encoding="utf-8", newline="") as f:
            yield from csv.DictReader(f)


def stream(kind: str, path: pathlib.Path, field: str):
    """Yield (clock, kind, seq, record); the clock never goes backwards, so file order is preserved."""
    clock = 0.0
    for i, rec in enumerate(read_file(path)):
        t = parse_ts(rec.get(field) or rec.get("updated_at") or rec.get("date"))
        clock = max(clock, t.timestamp() if t else clock)
        yield clock, kind, i, rec


class Worker(threading.Thread):
    def __init__(self, q, host, port, stats, lock, retries):
        super().__init__(daemon=True)
        self.q, self.host, self.port, self.stats, self.lock, self.retries = q, host, port, stats, lock, retries
        self.conn = None

    def _bump(self, key, msg=None):
        with self.lock:
            self.stats[key] += 1
            if msg and len(self.stats["samples"]) < 5:
                self.stats["samples"].append(msg)

    def _post(self, path, body):
        data = json.dumps(body).encode()
        for attempt in range(self.retries + 1):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
                self.conn.request("POST", path, data, {"Content-Type": "application/json"})
                resp = self.conn.getresponse()
                text = resp.read()
                if resp.status < 500:
                    self._bump(f"http_{resp.status}", (path, resp.status, text[:120]) if resp.status >= 400 else None)
                    return
                self._bump("retried_5xx")
            except (OSError, http.client.HTTPException):
                self._bump("retried_transport")
                try:
                    self.conn and self.conn.close()
                finally:
                    self.conn = None
            time.sleep(min(0.2 * 2 ** attempt, 3))
        self._bump("failed")

    def run(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            self._post(*item)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--data-dir", default=str(pathlib.Path(__file__).resolve().parents[1]))
    ap.add_argument("--concurrency", type=int, default=15)
    ap.add_argument("--only", choices=["all", *FILES], default="all")
    ap.add_argument("--mode", choices=["interleave", "sequential"], default="interleave")
    ap.add_argument("--batch-size", type=int, default=1, help="events per /collect request (1 = pixel-like)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N records (testing)")
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--no-refresh", dest="refresh", action="store_false",
                    help="don't ask the service to rebuild derived tables at the end")
    a = ap.parse_args()

    data = pathlib.Path(a.data_dir)
    streams = []
    for k in (list(FILES) if a.only == "all" else [a.only]):
        name, _, field = FILES[k]
        if (data / name).exists():
            streams.append(stream(k, data / name, field))
        else:
            print(f"[skip] {data / name} not found")
    if not streams:
        sys.exit("no input files found")
    merged = heapq.merge(*streams, key=lambda x: (x[0], x[1], x[2])) if a.mode == "interleave" \
        else (x for s in streams for x in s)

    u = urlparse(a.url)
    stats, lock = Counter(), threading.Lock()
    stats["samples"] = []
    q: queue.Queue = queue.Queue(maxsize=a.concurrency * 2)
    workers = [Worker(q, u.hostname, u.port or 80, stats, lock, a.retries) for _ in range(a.concurrency)]
    for w in workers:
        w.start()

    sent, n, batch = Counter(), 0, []
    t0 = last = time.perf_counter()
    for _, kind, _, rec in merged:
        if a.limit and n >= a.limit:
            break
        n += 1
        sent[kind] += 1
        if kind == "events" and a.batch_size > 1:
            batch.append(rec)
            if len(batch) < a.batch_size:
                continue
            q.put((FILES[kind][1], batch))
            batch = []
        else:
            q.put((FILES[kind][1], rec))
        if time.perf_counter() - last > 2:
            last = time.perf_counter()
            print(f"  sent {n:>7,} records  {n / (last - t0):6.0f}/s", flush=True)
    if batch:
        q.put((FILES["events"][1], batch))
    for _ in workers:
        q.put(None)
    for w in workers:
        w.join()
    dt = time.perf_counter() - t0
    if a.refresh:
        c = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=300)
        c.request("POST", "/admin/refresh")
        print("refresh:", c.getresponse().read().decode())

    samples = stats.pop("samples")
    print(f"\nDone in {dt:.1f}s ({n / dt:.0f} records/s), {a.concurrency} concurrent connections")
    print("records sent:", dict(sent))
    print("responses   :", dict(sorted(stats.items())))
    for s in samples:
        print("  sample error:", s)
    if stats["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
