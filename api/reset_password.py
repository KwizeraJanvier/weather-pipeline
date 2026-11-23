"""Reset a user's password - the app has no "forgot password" flow.

The new password is typed at a hidden prompt, never passed on the command line.

    # local Docker Postgres (the defaults in db.py point at localhost)
    python api/reset_password.py you@example.com

    # Neon: this Mac can't reach port 5432, so print an UPDATE to paste into
    # Neon's web SQL Editor instead
    python api/reset_password.py you@example.com --sql-only
"""
import argparse
import getpass
import sys

from auth import get_user_by_email, hash_password
from db import execute


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email")
    parser.add_argument("--sql-only", action="store_true", help="print the UPDATE instead of running it")
    args = parser.parse_args()

    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat new password: "):
        sys.exit("Passwords don't match - nothing changed.")
    password_hash = hash_password(password)

    if args.sql_only:
        email = args.email.replace("'", "''")
        print(f"UPDATE app.users SET password_hash = '{password_hash}' WHERE email = '{email}';")
        return

    if not get_user_by_email(args.email):
        sys.exit(f"No account with email {args.email} - nothing changed.")
    execute("UPDATE app.users SET password_hash = %s WHERE email = %s", (password_hash, args.email))
    print(f"Password updated for {args.email}.")


if __name__ == "__main__":
    main()
