#!/usr/bin/env python3
"""Add (or update) one Shoreline account on the server.

Run inside the Docker container so it uses the live database:

    docker-compose exec web python scripts/add_user.py toby --admin
    docker-compose exec web python scripts/add_user.py hop

It asks for the password (nothing shows while typing), so real passwords never go into
the GitHub repo. If the username already exists, its password and role are updated.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app, db  # noqa: E402  (loads every model)
from model.user import User  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Add or update a Shoreline account")
    parser.add_argument("uid", help="username to log in with")
    parser.add_argument("--name", help="display name (default: the username, capitalized)")
    parser.add_argument("--admin", action="store_true", help="give the account the Admin role")
    args = parser.parse_args()

    password = getpass.getpass(f"Password for {args.uid}: ")
    if len(password) < 6:
        sys.exit("Password must be at least 6 characters.")
    if getpass.getpass("Type it again: ") != password:
        sys.exit("Passwords didn't match. Nothing changed.")

    role = "Admin" if args.admin else "User"
    with app.app_context():
        user = User.query.filter_by(_uid=args.uid).first()
        if user is None:
            user = User(name=args.name or args.uid.capitalize(), uid=args.uid, password=password, role=role)
            db.session.add(user)
            action = "Created"
        else:
            user.set_password(password)
            user._role = role
            action = "Updated"
        user.active = True
        db.session.commit()
        print(f"{action} {args.uid} ({role}).")


if __name__ == "__main__":
    main()
