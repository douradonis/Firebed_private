#!/usr/bin/env python3
"""
Set a single admin user for the application.

Usage: run this script in the workspace. It will create or update the local user
`adonis.douramanis@gmail.com` with the provided password and mark it as the only admin.
If Firebase is configured it will create or update the Firebase user and store the UID locally.
"""
import os
import sys
from getpass import getpass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from models import db, User
import firebase_config
from firebase_auth_handlers import FirebaseAuthHandler

ADMIN_EMAIL = 'adonis.douramanis@gmail.com'
ADMIN_PASSWORD = 'passpadeisou16!'


def init_app():
    local_app = Flask(__name__)
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    local_app.config.setdefault('SQLALCHEMY_DATABASE_URI', os.getenv('DATABASE_URL') or 'sqlite:///' + os.path.join(BASE_DIR, 'firebed.db'))
    local_app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    db.init_app(local_app)
    return local_app


def set_admin(local_app, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    with local_app.app_context():
        # Clear other admin flags
        print("Clearing other admin flags...")
        users = User.query.filter_by(is_admin=True).all()
        for u in users:
            u.is_admin = False
        db.session.commit()

        # Find or create admin
        admin = User.query.filter_by(email=email).first()
        created = False
        if not admin:
            admin = User(username=email)
            admin.email = email
            admin.set_password(password)
            admin.is_admin = True
            db.session.add(admin)
            db.session.commit()
            created = True
            print(f"Created local admin: {email} (id={admin.id})")
        else:
            admin.set_password(password)
            admin.is_admin = True
            db.session.commit()
            print(f"Updated local admin: {email} (id={admin.id})")

        # Ensure Firebase user exists and record uid
        try:
            if firebase_config.init_firebase():
                # check if user exists in Firebase
                try:
                    fb_user = firebase_config.firebase_get_user_by_email(email)
                    if fb_user and 'uid' in fb_user:
                        uid = fb_user['uid']
                        admin.firebase_uid = uid
                        admin.email_verified = fb_user.get('email_verified', False)
                        db.session.commit()
                        print(f"Linked existing Firebase user: {email} (uid={uid})")
                    else:
                        ok, uid, err = FirebaseAuthHandler.register_user(email, password, display_name=email.split('@')[0])
                        if ok and uid:
                            admin.firebase_uid = uid
                            admin.email_verified = False
                            db.session.commit()
                            print(f"Created Firebase user and linked uid={uid}")
                        else:
                            print(f"Firebase user creation skipped or failed: {err}")
                except Exception as e:
                    print(f"Firebase check/create failed: {e}")
        except Exception:
            print("Firebase not configured; skipped cloud user creation")

        print("Done. Admin credentials:")
        print(f"  email: {email}")
        print(f"  password: {password}")
        if created:
            print("Admin was created locally.")


def main():
    print("This script will set the unique admin to adonis.douramanis@gmail.com")
    confirm = input("Type 'YES' to proceed: ")
    if confirm.strip() != 'YES':
        print('Aborted')
        return 1

    app = init_app()
    set_admin(app)
    return 0


if __name__ == '__main__':
    sys.exit(main())
