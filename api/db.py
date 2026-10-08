import os

import psycopg2
import psycopg2.extras


def _connect(user: str, password: str):
    return psycopg2.connect(
        host=os.environ.get("WAREHOUSE_DB_HOST", "localhost"),
        port=os.environ.get("WAREHOUSE_DB_PORT", "5432"),
        dbname=os.environ.get("WAREHOUSE_DB_NAME", "warehouse"),
        user=user,
        password=password,
        # See extraction/fetch_weather.py - libpq's GSSAPI credential probe
        # can hang forever on this macOS version. We don't use Kerberos, so
        # disable the probe entirely.
        gssencmode="disable",
    )


def get_connection():
    """The app's own connection - full read/write, used for the app's own
    queries (weather/forecast/rain-stats, and reading/writing app.users).
    Never used to run a user-supplied query - see get_readonly_connection.
    """
    return _connect(
        os.environ.get("WAREHOUSE_DB_USER", "warehouse"),
        os.environ.get("WAREHOUSE_DB_PASSWORD", "warehouse"),
    )


def get_readonly_connection():
    """A connection as app_readonly - a Postgres role with SELECT-only grants
    on raw/staging/marts and NO access to the app schema (see
    sql/init_app_schema.sql). This is the only connection ever used to run a
    query someone typed into the web UI, so even a bug in the app's own
    SELECT-only check can't turn into a write or a password-hash leak.
    """
    return _connect(
        os.environ.get("APP_READONLY_DB_USER", "app_readonly"),
        os.environ.get("APP_READONLY_DB_PASSWORD", "app_readonly"),
    )


def query(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def execute(sql: str, params: tuple = ()) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()
