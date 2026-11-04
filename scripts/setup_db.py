#!/usr/bin/env python
"""One-time setup: create the project's PostgreSQL databases and write a `.env` with the connection string.

    python scripts/setup_db.py                       # prompts for host / port / user / password (typed locally)
    python scripts/setup_db.py --host localhost --port 5432 --user postgres

What it does
  * connects to the server's maintenance database ("postgres") with the credentials you give,
  * creates `urbanthread` (the app) and `urbanthread_test` (the test-suite; its tests TRUNCATE tables,
    so it must never be the app database) if they do not exist,
  * writes DATABASE_URL and TEST_DATABASE_URL to `.env` (git-ignored; the app reads it on start).
The password is only used for this connection and for the local `.env` file; nothing is sent anywhere else.
"""
from __future__ import annotations

import argparse
import getpass
import os
import pathlib
import sys
from urllib.parse import quote

import psycopg
from psycopg import sql


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--user")
    ap.add_argument("--password", help="avoid: shows in shell history. Prefer the prompt or the PGPASSWORD env var")
    ap.add_argument("--db", default="urbanthread")
    ap.add_argument("--test-db", default="urbanthread_test")
    ap.add_argument("--env-file", default=str(pathlib.Path(__file__).resolve().parents[1] / ".env"))
    ap.add_argument("--force", action="store_true", help="overwrite an existing .env")
    a = ap.parse_args()

    interactive = sys.stdin.isatty()
    host = a.host or (input("PostgreSQL host [localhost]: ").strip() if interactive else "") or "localhost"
    port = a.port or int((input("Port [5432]: ").strip() if interactive else "") or 5432)
    user = a.user or (input("User [postgres]: ").strip() if interactive else "") or "postgres"
    password = a.password if a.password is not None else os.environ.get("PGPASSWORD")
    if password is None:
        password = getpass.getpass(f"Password for {user}@{host}:{port} (typing is hidden): ") if interactive else ""

    try:
        admin = psycopg.connect(host=host, port=port, user=user, password=password, dbname="postgres", autocommit=True, connect_timeout=8)
    except psycopg.OperationalError as e:
        print(f"\nCould not connect to {user}@{host}:{port}\n  {str(e).strip()}\n\nCheck the server is running and the password is right.")
        return 1

    with admin:
        print(f"Connected: {admin.execute('select version()').fetchone()[0].split(',')[0]}")
        have = {r[0] for r in admin.execute("select datname from pg_database")}
        for name in (a.db, a.test_db):
            if name in have:
                print(f"  database '{name}' already exists")
            else:
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                print(f"  created database '{name}'")

    cred = f"{quote(user, safe='')}:{quote(password, safe='')}"
    env = (f"DATABASE_URL=postgresql://{cred}@{host}:{port}/{a.db}\n"
           f"TEST_DATABASE_URL=postgresql://{cred}@{host}:{port}/{a.test_db}\n")
    path = pathlib.Path(a.env_file)
    if path.exists() and not a.force:
        print(f"\n{path} already exists, so I left it alone (use --force to overwrite). Put these lines in it:\n\n{env.replace(password, '***') if password else env}")
    else:
        path.write_text(env, encoding="utf-8")
        print(f"\nWrote {path} (git-ignored).")
    print("Next:  python -m uvicorn app.main:app --port 8000   then   python sender/send.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
