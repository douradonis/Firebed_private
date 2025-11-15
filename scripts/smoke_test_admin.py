"""Smoke test for admin API endpoints using Flask test client.

This script simulates an authenticated admin by setting the Flask session
_user_id to ADMIN_USER_ID and calls /admin/api/groups, /admin/api/users and
/admin/api/activity. It also tests logout clears session['active_group'].

Run: python scripts/smoke_test_admin.py
"""
import os
import sys
import json

# ensure project root on sys.path when running from scripts/
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db

print('Starting smoke test')
with app.app_context():
    try:
        db.create_all()
    except Exception:
        pass

admin_id = int(os.getenv('ADMIN_USER_ID') or app.config.get('ADMIN_USER_ID', 0) or 0)
print('Admin id used for test:', admin_id)

with app.test_client() as c:
    # set up a simulated logged-in admin session
    with c.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True
        # also set a stale active_group to test logout clearing
        sess['active_group'] = 'stale_group_test'

    endpoints = [
        ('GET', '/admin/api/groups'),
        ('GET', '/admin/api/users'),
        ('GET', '/admin/api/activity?group=&limit=50')
    ]

    results = {}
    for method, path in endpoints:
        print('\nCalling', method, path)
        if method == 'GET':
            resp = c.get(path)
        else:
            resp = c.post(path)
        print('Status:', resp.status_code)
        data = None
        try:
            data = resp.get_json()
        except Exception:
            try:
                data = resp.get_data(as_text=True)
            except Exception:
                data = '<no body>'
        print('Body:', json.dumps(data, indent=2, ensure_ascii=False) if isinstance(data, dict) else data)
        results[path] = (resp.status_code, data)

    # test logout clears active_group — try known logout endpoints
    print('\nTesting logout clears active_group...')
    logout_paths = ['/auth/logout', '/firebase-auth/logout', '/logout']
    resp = None
    for lp in logout_paths:
        print('Trying logout path:', lp)
        resp = c.get(lp, follow_redirects=True)
        print('Status for', lp, resp.status_code)
        if resp.status_code in (200, 302):
            print('Logout succeeded at', lp)
            break
    if resp is None:
        print('No logout response captured')
    with c.session_transaction() as sess:
        active = sess.get('active_group')
    print('Session active_group after logout attempt:', repr(active))

print('\nSmoke test complete')
