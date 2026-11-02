"""Create tables and seed default users on a fresh deploy (Render start step).

Runs the same initializers as `flask custom generate_data`, but as a plain script:
the Flask CLI can't load this app because the package root is named __init__.py.
Each step is independent so one failing seed doesn't block the server from starting.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402  (registers blueprints/models)
from __init__ import app, db  # noqa: E402

STEPS = [main.initUsers, main.initMicroblogs, main.initPersonas, main.initPersonaUsers]

with app.app_context():
    db.create_all()
    for step in STEPS:
        try:
            step()
            print(f"render_init: {step.__name__} ok")
        except Exception as err:  # keep going; the app can run without seed data
            db.session.rollback()
            print(f"render_init: {step.__name__} skipped: {err}")
