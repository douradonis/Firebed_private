#!/usr/bin/env python3
"""
Wipe all local and Firebase data, preserving a single administrator account.

Behavior:
- Finds a local admin user to keep (prefer username 'admin', else first is_admin=True, else first user)
- Backs up the admin's local profile to a JSON file in data/_admin_backup.json
- Deletes all other local users, groups, tokens, backups, and files under `data/`, `uploads/`, `exports/` etc.
- If Firebase is enabled, deletes Firebase Realtime Database top-level paths and removes all Firebase Auth users except the admin's Firebase UID (if found).

Use with caution - this is destructive. Only run if you want a clean environment.
"""
import os
import sys
import json
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Avoid importing the full `app` module to prevent starting the dev server.
from flask import Flask
from models import db, User, Group, UserGroup, VerificationToken
import firebase_config

DATA_DIR = os.path.join(os.getcwd(), 'data')
UPLOADS_DIR = os.path.join(os.getcwd(), 'uploads')
EXPORTS_DIR = os.path.join(os.getcwd(), 'exports')
BACKUPS_DIR = os.path.join(DATA_DIR, '_backups')
ADMIN_BACKUP_FILE = os.path.join(DATA_DIR, '_admin_backup.json')


def safe_remove_dir(p):
    try:
        if os.path.exists(p):
            shutil.rmtree(p)
            print(f"Removed directory: {p}")
    except Exception as e:
        print(f"Failed to remove {p}: {e}")


def wipe_local_keep_admin():
    # Create a minimal Flask app for DB context to avoid importing full application
    local_app = Flask(__name__)
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    local_app.config.setdefault('SQLALCHEMY_DATABASE_URI', os.getenv('DATABASE_URL') or 'sqlite:///' + os.path.join(BASE_DIR, 'firebed.db'))
    local_app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    db.init_app(local_app)
    with local_app.app_context():
        print("[LOCAL] Finding admin user to preserve...")
        admin_user = None
        # Prefer username 'admin'
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User.query.filter_by(is_admin=True).first()
        if not admin_user:
            admin_user = User.query.first()

        if not admin_user:
            print("No users found in local DB. Nothing to preserve.")
            return None

        print(f"[LOCAL] Preserving local admin: id={admin_user.id} username={admin_user.username} email={admin_user.email}")

        # Dump admin profile to file
        os.makedirs(DATA_DIR, exist_ok=True)
        admin_data = {
            'id': admin_user.id,
            'username': admin_user.username,
            'email': admin_user.email,
            'password_hash': admin_user.password_hash,
            'is_admin': bool(admin_user.is_admin),
            'firebase_uid': getattr(admin_user, 'firebase_uid', None)
        }
        with open(ADMIN_BACKUP_FILE, 'w', encoding='utf-8') as f:
            json.dump(admin_data, f, indent=2)
        print(f"[LOCAL] Admin profile backed up to {ADMIN_BACKUP_FILE}")

        # Delete other users
        print("[LOCAL] Deleting other users and related data from DB...")
        other_users = User.query.filter(User.id != admin_user.id).all()
        for u in other_users:
            try:
                # delete user_groups
                for ug in list(u.user_groups):
                    db.session.delete(ug)
                db.session.delete(u)
            except Exception as e:
                print(f"Failed to delete user {u.id}: {e}")
        db.session.commit()

        # Delete all groups
        print("[LOCAL] Deleting all groups...")
        groups = Group.query.all()
        for g in groups:
            try:
                # delete user_groups
                for ug in list(g.user_groups):
                    db.session.delete(ug)
                db.session.delete(g)
            except Exception as e:
                print(f"Failed to delete group {g.id}: {e}")
        db.session.commit()

        # Delete verification tokens
        print("[LOCAL] Deleting verification tokens...")
        try:
            VerificationToken.query.delete()
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Clean backups and data directories except we keep the admin backup file
        print("[LOCAL] Cleaning data directories (data, uploads, exports)...")
        # remove everything under DATA_DIR except ADMIN_BACKUP_FILE
        if os.path.exists(DATA_DIR):
            for item in os.listdir(DATA_DIR):
                path = os.path.join(DATA_DIR, item)
                if os.path.abspath(path) == os.path.abspath(ADMIN_BACKUP_FILE):
                    continue
                safe_remove_dir(path)
        # remove uploads and exports
        safe_remove_dir(UPLOADS_DIR)
        safe_remove_dir(EXPORTS_DIR)

        print("[LOCAL] Local wipe complete. Admin profile preserved.")
        return admin_data


def wipe_firebase_except_admin(admin_data):
    # Initialize Firebase if possible
    print("[FIREBASE] Initializing Firebase (if configured)...")
    ok = firebase_config.init_firebase()
    if not ok:
        print("[FIREBASE] Firebase not configured or failed to initialize. Skipping cloud wipe.")
        return False

    print("[FIREBASE] Firebase initialized. Proceeding to delete RTDB data and Auth users (except admin)...")

    # Determine admin uid to keep
    admin_uid = admin_data.get('firebase_uid')
    admin_email = admin_data.get('email')
    if not admin_uid and admin_email:
        try:
            fb_user = firebase_config.firebase_get_user_by_email(admin_email)
            if fb_user:
                admin_uid = fb_user.get('uid')
        except Exception:
            admin_uid = None

    print(f"[FIREBASE] Admin UID to preserve: {admin_uid}")

    # Delete top-level RTDB paths
    paths_to_delete = ['users', 'groups', 'backups', 'activity_logs', 'group_encryption_keys', 'verification_token', 'user_groups']
    for p in paths_to_delete:
        try:
            firebase_config.firebase_delete_data(f'/{p}')
            print(f"[FIREBASE] Deleted path: /{p}")
        except Exception as e:
            print(f"[FIREBASE] Failed to delete /{p}: {e}")

    # Delete Firebase Auth users except admin
    try:
        import firebase_admin
        from firebase_admin import auth as fb_auth
        page = fb_auth.list_users()
        to_delete = []
        for user in page.iterate_all():
            uid = user.uid
            email = user.email
            if admin_uid and uid == admin_uid:
                print(f"[FIREBASE] Keeping admin user: {email} ({uid})")
                continue
            # If admin_uid not known, attempt to keep by matching admin_email
            if not admin_uid and admin_email and email == admin_email:
                print(f"[FIREBASE] Keeping admin by email match: {email} ({uid})")
                admin_uid = uid
                continue
            # otherwise queue for deletion
            to_delete.append((uid, email))

        for uid, email in to_delete:
            try:
                firebase_config.firebase_delete_user(uid)
                print(f"[FIREBASE] Deleted user: {email} ({uid})")
            except Exception as e:
                print(f"[FIREBASE] Failed to delete user {email} ({uid}): {e}")
    except Exception as e:
        print(f"[FIREBASE] Failed to list/delete Firebase auth users: {e}")

    print("[FIREBASE] Cloud wipe complete (where Firebase was configured).")
    return True


def restore_admin_local(admin_data):
    """Ensure admin record exists and is active with known password for testing."""
    local_app = Flask(__name__)
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    local_app.config.setdefault('SQLALCHEMY_DATABASE_URI', os.getenv('DATABASE_URL') or 'sqlite:///' + os.path.join(BASE_DIR, 'firebed.db'))
    local_app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    db.init_app(local_app)
    with local_app.app_context():
        print("[LOCAL] Restoring admin user in local DB (ensuring admin exists)")
        admin = None
        if 'id' in admin_data:
            admin = User.query.filter_by(username=admin_data.get('username')).first()
        if not admin:
            admin = User(username=admin_data.get('username'))
            admin.email = admin_data.get('email')
            # set a known password for testing
            admin.set_password('admin123')
            admin.is_admin = True
            admin.firebase_uid = admin_data.get('firebase_uid')
            db.session.add(admin)
            db.session.commit()
            print(f"[LOCAL] Admin recreated: {admin.username} (id={admin.id})")
        else:
            admin.is_admin = True
            admin.firebase_uid = admin_data.get('firebase_uid')
            admin.email = admin_data.get('email')
            # ensure password is set to admin123 for testing
            admin.set_password('admin123')
            db.session.commit()
            print(f"[LOCAL] Admin updated: {admin.username} (id={admin.id})")


def main():
    print("*** Wipe Script: destructive action ahead ***")
    confirm = input("Type 'WIPE' to proceed and destroy local/cloud data (keep admin only): ")
    if confirm.strip() != 'WIPE':
        print("Aborting.")
        return 1

    admin_data = wipe_local_keep_admin()
    if not admin_data:
        print("No admin found locally to preserve. Aborting to avoid accidental deletion.")
        return 1

    # Wipe Firebase except admin
    wipe_firebase_except_admin(admin_data)

    # Restore admin in case it was removed
    restore_admin_local(admin_data)

    print("\nWipe complete. Local environment reset with admin preserved.")
    print(f"Admin username: {admin_data.get('username')} password: admin123")
    print("You can now login as admin and reconfigure the system.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
