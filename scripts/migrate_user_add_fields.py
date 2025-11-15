#!/usr/bin/env python3
"""Migration script: add new User fields and populate existing values.

This script will:
- Add columns `email`, `firebase_uid`, `created_at`, `last_login` to `user` table if missing.
- Populate `email` with the value of `username` for existing records.
- Populate `firebase_uid` from `pw_hash` for records where `pw_hash` does not look like a hashed password.

Note: This is a minimal migration helper for development. For production, use Alembic.
"""
import os
import sys
from datetime import datetime
from sqlalchemy import inspect
from sqlalchemy.sql import text

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app
from models import db, User

def column_exists(engine, table, column):
    try:
        insp = inspect(engine)
        cols = [c['name'] for c in insp.get_columns(table)]
        return column in cols
    except Exception:
        return False

def add_column(engine, table, column_sql):
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_sql}"))
        print('Added column:', column_sql)
    except Exception as e:
        print('Error adding column:', e)

def main():
    with app.app_context():
        engine = db.engine

        # Add email if missing
        if not column_exists(engine, 'user', 'email'):
            add_column(engine, 'user', "email VARCHAR(150)")

        # Add firebase_uid
        if not column_exists(engine, 'user', 'firebase_uid'):
            add_column(engine, 'user', "firebase_uid VARCHAR(128)")

        # created_at and last_login
        if not column_exists(engine, 'user', 'created_at'):
            add_column(engine, 'user', "created_at DATETIME")
        if not column_exists(engine, 'user', 'last_login'):
            add_column(engine, 'user', "last_login DATETIME")

        # update existing rows
        users = User.query.all()
        print('Found users:', len(users))
        for u in users:
            changed = False
            if not getattr(u, 'email', None):
                u.email = u.username
                changed = True
            if not getattr(u, 'firebase_uid', None) and getattr(u, 'pw_hash', None):
                # heuristics: if pw_hash string does not contain a ':' it is likely a UID
                s = u.pw_hash or ''
                if ':' not in s and len(s) > 6 and len(s) < 128:
                    u.firebase_uid = s
                    changed = True
            if not getattr(u, 'created_at', None):
                u.created_at = datetime.utcnow()
                changed = True
            if changed:
                print('Updating user', u.id, u.username)
                try:
                    db.session.add(u)
                    db.session.commit()
                except Exception as e:
                    print('Failed to update user', u.id, e)

        print('Migration complete')

if __name__ == '__main__':
    main()
