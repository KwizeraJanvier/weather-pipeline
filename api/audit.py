from db import execute, query


def log_action(email: str, action: str, user_id: int | None = None, detail: str | None = None) -> None:
    execute(
        "INSERT INTO app.audit_log (user_id, email, action, detail) VALUES (%s, %s, %s, %s)",
        (user_id, email, action, detail),
    )


def recent_entries(limit: int = 100) -> list[dict]:
    return query(
        "SELECT id, email, action, detail, created_at FROM app.audit_log ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
