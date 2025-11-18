#!/usr/bin/env python3
"""Create an admin user and print the assigned ID.

Usage:
  python scripts/create_admin.py --username admin@example.com --password "S3cureP@ss"

This script requires the app to be importable and the DB configured (run inside project venv).
"""
import argparse
import sys
import os

# Ensure project root is on sys.path so `from app import app` works when
# this script is run from the `scripts/` directory.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
  sys.path.insert(0, ROOT)

try:
  from app import app
  from models import db, User
except Exception as e:
  print('Failed to import application modules. Make sure you run this from the project root or have the project in PYTHONPATH.')
  print('Error:', e)
  sys.exit(2)

parser = argparse.ArgumentParser()
parser.add_argument('--username', required=True, help='Admin username (email recommended)')
parser.add_argument('--password', required=True, help='Admin password')
args = parser.parse_args()

with app.app_context():
    db.create_all()
    existing = User.query.filter_by(username=args.username).first()
    if existing:
        print(f"User already exists: id={existing.id}, username={existing.username}")
        print(f"Set ADMIN_USER_ID={existing.id} in your .env or secret manager")
    else:
        admin = User(username=args.username)
        admin.set_password(args.password)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin created: id={admin.id}, username={admin.username}")
        print(f"Set ADMIN_USER_ID={admin.id} in your .env or secret manager")
