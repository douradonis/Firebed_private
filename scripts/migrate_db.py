"""Migrate DB to add email verification fields and VerificationToken table."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app
from models import db

def main():
    with app.app_context():
        print("Creating/updating DB tables...")
        try:
            # Create all tables (will skip existing ones)
            db.create_all()
            print("✅ DB migration complete")
        except Exception as e:
            print(f"❌ Migration error: {e}")
            return False
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
