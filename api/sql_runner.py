import re

import psycopg2.extras
from fastapi import HTTPException

from db import get_readonly_connection

# The real protection is that this always runs as app_readonly, a Postgres
# role with SELECT-only grants and no access to the app schema at all (see
# sql/init_app_schema.sql) - even a bug here can't turn into a write or a
# password-hash leak. This check is a second layer: reject anything that
# isn't obviously a single read-only query, so mistakes get a clear error
# instead of a raw Postgres permission-denied message.
_BLOCKED_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create)\b",
    re.IGNORECASE,
)


def run_query(sql: str) -> dict:
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise HTTPException(status_code=400, detail="Empty query")
    if ";" in stripped:
        raise HTTPException(status_code=400, detail="Only a single statement is allowed")
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")
    if _BLOCKED_KEYWORDS.search(stripped):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed")

    conn = get_readonly_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(stripped)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description] if cur.description else []
            return {"columns": columns, "rows": [dict(row) for row in rows]}
    finally:
        conn.close()
