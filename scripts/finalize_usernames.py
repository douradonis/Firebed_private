"""Finalize usernames: remove '_smoketest' suffixes and attempt to produce clean usernames.

Strategy:
- Desired username is `email` (if present) else username with '_smoketest' removed.
- If multiple users map to the same desired username:
  - Attempt to merge users when emails/fb uid match (move groups, keep strongest attributes).
  - If merge not safe, keep the primary desired username for the earliest user and append _<id> to others (fallback).

Run: python3 scripts/finalize_usernames.py
"""
import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app
from models import db, User, UserGroup
from admin_panel import admin_list_all_users


def normalize_candidate(u: User) -> str:
    # Prefer email if available and not empty
    email = (u.email or '').strip()
    if email:
        return email.lower()
    uname = (u.username or '').strip()
    # remove smoketest occurrences
    uname = uname.replace('_smoketest_smoketest', '_smoketest')
    while '_smoketest_smoketest' in uname:
        uname = uname.replace('_smoketest_smoketest', '_smoketest')
    if uname.endswith('_smoketest'):
        uname = uname[:-len('_smoketest')]
    return uname


def merge_users(primary: User, secondary: User):
    # Move groups from secondary to primary (avoid duplicates)
    try:
        for ug in list(secondary.user_groups):
            exists = False
            for pug in primary.user_groups:
                if pug.group_id == ug.group_id:
                    exists = True
                    # if secondary had admin role, promote primary's role
                    if ug.role == 'admin' and pug.role != 'admin':
                        pug.role = 'admin'
                    break
            if not exists:
                # reassign ownership
                ug.user_id = primary.id
                primary.user_groups.append(ug)
        # Consolidate flags
        primary.is_admin = primary.is_admin or secondary.is_admin
        # Prefer primary's firebase_uid if present, else use secondary
        if not getattr(primary, 'firebase_uid', None) and getattr(secondary, 'firebase_uid', None):
            primary.firebase_uid = secondary.firebase_uid
        # Prefer password hash: keep primary unless empty
        if not primary.password_hash and secondary.password_hash:
            primary.password_hash = secondary.password_hash
        db.session.add(primary)
        # delete secondary
        db.session.delete(secondary)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print('Merge failed:', e)
        return False


def main():
    with app.app_context():
        users = User.query.order_by(User.id).all()
        desired_map = {}
        for u in users:
            cand = normalize_candidate(u)
            if not cand:
                cand = f'user_{u.id}'
            desired_map.setdefault(cand, []).append(u)

        changed = 0
        unresolved = []
        for cand, lst in desired_map.items():
            if len(lst) == 1:
                u = lst[0]
                if u.username != cand:
                    # ensure uniqueness
                    exists = User.query.filter(User.username == cand).first()
                    if exists and exists.id != u.id:
                        # conflict; fallback
                        newname = f"{cand}_{u.id}"
                        print(f"Conflict setting {u.id} -> {cand}; using {newname}")
                        u.username = newname
                    else:
                        print(f"Setting user {u.id} username -> {cand}")
                        u.username = cand
                    db.session.add(u)
                    changed += 1
            else:
                # multiple users want same candidate
                primary = lst[0]
                print(f"Multiple users ({[x.id for x in lst]}) map to '{cand}', choosing primary {primary.id}")
                for sec in lst[1:]:
                    # try to merge if safe: same email or same firebase_uid
                    safe_to_merge = False
                    if (primary.email and sec.email and primary.email == sec.email) or (getattr(primary,'firebase_uid',None) and getattr(sec,'firebase_uid',None) and primary.firebase_uid == sec.firebase_uid):
                        safe_to_merge = True
                    if safe_to_merge:
                        ok = merge_users(primary, sec)
                        if ok:
                            print(f"Merged user {sec.id} into {primary.id}")
                        else:
                            print(f"Failed to merge {sec.id} into {primary.id}; will fallback to rename")
                            sec.username = f"{cand}_{sec.id}"
                            db.session.add(sec)
                            changed += 1
                    else:
                        # cannot auto-merge; rename secondary to keep unique
                        sec.username = f"{cand}_{sec.id}"
                        db.session.add(sec)
                        changed += 1
                # ensure primary has desired username
                exists = User.query.filter(User.username == cand).first()
                if exists and exists.id != primary.id:
                    # someone else occupies the name; change primary if needed
                    primary.username = f"{cand}_{primary.id}"
                    db.session.add(primary)
                    changed += 1
                else:
                    if primary.username != cand:
                        primary.username = cand
                        db.session.add(primary)
                        changed += 1
        if changed:
            try:
                db.session.commit()
                print(f"Committed {changed} username changes")
            except Exception as e:
                print('Commit error:', e)
                db.session.rollback()
        else:
            print('No username changes required')

if __name__ == '__main__':
    main()
