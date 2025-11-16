"""Clean duplicate 'smoketest' suffixes from User.username and User.email.

Run: python scripts/clean_smoketest.py
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app
from models import db, User

def normalize_smoketest(value: str) -> str:
    if not value:
        return value
    # collapse repeated '_smoketest' occurrences
    while '_smoketest_smoketest' in value:
        value = value.replace('_smoketest_smoketest', '_smoketest')
    # If it ends up with multiple separated by more underscores, collapse
    value = value.replace('__', '_')
    return value

def main():
    with app.app_context():
        users = User.query.all()
        changed = 0
        for u in users:
            orig_username = u.username or ''
            orig_email = (u.email or '')
            new_username = normalize_smoketest(orig_username)
            new_email = normalize_smoketest(orig_email)
            # If username looks like an email plus '_smoketest', remove the suffix
            if new_username and new_username.endswith('_smoketest') and '@' in new_username:
                candidate = new_username[:-len('_smoketest')]
                # prefer to set username exactly to the email part (no suffix)
                # but ensure uniqueness: if candidate already exists for another user, append _<id>
                exists = User.query.filter(User.username == candidate).first()
                if exists and exists.id != u.id:
                    candidate = f"{candidate}_{u.id}"
                new_username = candidate
            # strip whitespace/newlines from email
            new_email = (new_email or '').strip()
            if new_username != orig_username or new_email != orig_email:
                print(f"Updating user {u.id}:\n  username: {orig_username} -> {new_username}\n  email: {orig_email} -> {new_email}")
                u.username = new_username
                if new_email:
                    u.email = new_email
                db.session.add(u)
                changed += 1
        if changed:
            try:
                db.session.commit()
                print(f"Committed changes for {changed} users")
            except Exception as e:
                print('Failed to commit:', e)
                db.session.rollback()
        else:
            print('No users required changes')

if __name__ == '__main__':
    main()
