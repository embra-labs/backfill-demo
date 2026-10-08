"""Connections only to the disposable demo database; fresh schema per scenario."""
import os
import re

import psycopg
from psycopg import sql


def connect(schema):
    if not re.fullmatch(r"demo_[a-z0-9_]+", schema):
        raise ValueError("Not a demo schema")
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True,
                           connect_timeout=10)
    if conn.execute("SELECT current_database()").fetchone()[0] != "backfill_demo":
        conn.close()
        raise ValueError("Refusing to run outside backfill_demo")
    conn.execute(sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema)))
    conn.execute("SET statement_timeout = '10s'")
    conn.execute("SET lock_timeout = '5s'")
    return conn
