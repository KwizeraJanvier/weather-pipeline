import os

import psycopg2
import psycopg2.extras


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("WAREHOUSE_DB_HOST", "localhost"),
        port=os.environ.get("WAREHOUSE_DB_PORT", "5432"),
        dbname=os.environ.get("WAREHOUSE_DB_NAME", "warehouse"),
        user=os.environ.get("WAREHOUSE_DB_USER", "warehouse"),
        password=os.environ.get("WAREHOUSE_DB_PASSWORD", "warehouse"),
        # See extraction/fetch_weather.py - libpq's GSSAPI credential probe
        # can hang forever on this macOS version. We don't use Kerberos, so
        # disable the probe entirely.
        gssencmode="disable",
    )


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
