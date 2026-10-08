import bcrypt
from fastapi import Depends, HTTPException, Request

from db import execute, query


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def get_user_by_email(email: str) -> dict | None:
    rows = query("SELECT id, email, password_hash, role FROM app.users WHERE email = %s", (email,))
    return rows[0] if rows else None


def get_user_by_id(user_id: int) -> dict | None:
    rows = query("SELECT id, email, role FROM app.users WHERE id = %s", (user_id,))
    return rows[0] if rows else None


def user_count() -> int:
    return query("SELECT count(*) AS n FROM app.users")[0]["n"]


def create_user(email: str, password: str) -> dict:
    if get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    # The very first account on a fresh install becomes admin automatically
    # (so there's someone who can use the SQL query tool); everyone after
    # that is a viewer by default. There's no UI to promote a user - do it
    # by hand if needed: UPDATE app.users SET role = 'admin' WHERE email = ...
    role = "admin" if user_count() == 0 else "viewer"
    password_hash = hash_password(password)
    execute(
        "INSERT INTO app.users (email, password_hash, role) VALUES (%s, %s, %s)",
        (email, password_hash, role),
    )
    return get_user_by_email(email)


def get_current_user(request: Request) -> dict:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    user = get_user_by_id(user_id)
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
