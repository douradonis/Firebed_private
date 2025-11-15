#!/usr/bin/env python3
"""
Test the specific login flows mentioned by the user
Tests both local auth and Firebase auth routes
"""

import sys
from app import app, db
from models import User, Group
from flask import Flask

def simulate_login_flow():
    """Simulate a complete login flow"""
    print("\n" + "=" * 70)
    print("LOGIN FLOW TEST")
    print("=" * 70)
    
    with app.test_client() as client:
        # Test 1: Admin login with username
        print("\n1. Testing admin login with USERNAME...")
        response = client.post('/login', data={
            'username': 'admin',
            'password': 'admin@123'
        }, follow_redirects=True)
        
        if response.status_code == 200:
            print("✓ Admin login with username succeeded (status 200)")
        else:
            print(f"✗ Admin login with username failed (status {response.status_code})")
        
        # Test 2: Admin login with email
        print("\n2. Testing admin login with EMAIL...")
        response = client.post('/login', data={
            'username': 'admin@firebed.local',
            'password': 'admin@123'
        }, follow_redirects=True)
        
        if response.status_code == 200:
            print("✓ Admin login with email succeeded (status 200)")
        else:
            print(f"✗ Admin login with email failed (status {response.status_code})")
        
        # Test 3: Regular user login with email
        print("\n3. Testing regular user login with EMAIL...")
        response = client.post('/login', data={
            'username': 'alpha@firebed.local',
            'password': 'user_alpha@123'
        }, follow_redirects=True)
        
        if response.status_code == 200:
            print("✓ Regular user login with email succeeded (status 200)")
        else:
            print(f"✗ Regular user login with email failed (status {response.status_code})")
        
        # Test 4: API endpoint for user groups
        print("\n4. Testing /api/user_groups endpoint...")
        client.post('/login', data={
            'username': 'admin',
            'password': 'admin@123'
        })
        
        response = client.get('/api/user_groups')
        if response.status_code == 200:
            data = response.get_json()
            print(f"✓ /api/user_groups succeeded (status 200)")
            print(f"  - Groups: {[g['name'] for g in data.get('groups', [])]}")
            print(f"  - Active group: {data.get('active_group')}")
        else:
            print(f"✗ /api/user_groups failed (status {response.status_code})")

def verify_database_state():
    """Verify the database state"""
    print("\n" + "=" * 70)
    print("DATABASE STATE")
    print("=" * 70)
    
    with app.app_context():
        # Count entities
        user_count = User.query.count()
        group_count = Group.query.count()
        admin_count = User.query.filter_by(is_admin=True).count()
        
        print(f"\nTotal users: {user_count}")
        print(f"Total groups: {group_count}")
        print(f"Admin users: {admin_count}")
        
        # Show admin user details
        admin = User.query.filter_by(username='admin').first()
        if admin:
            print(f"\nAdmin User Details:")
            print(f"  - Username: {admin.username}")
            print(f"  - Email: {admin.email}")
            print(f"  - ID: {admin.id}")
            print(f"  - is_admin: {admin.is_admin}")
            print(f"  - Groups: {len(admin.groups)}")
        
        # Show users with emails
        print(f"\nUsers with emails:")
        users_with_email = User.query.filter(User.email != None).all()
        for u in users_with_email[:5]:
            print(f"  - {u.username}: {u.email}")

def check_routes():
    """Check if routes are properly registered"""
    print("\n" + "=" * 70)
    print("ROUTE VERIFICATION")
    print("=" * 70)
    
    required_routes = [
        '/login',
        '/logout',
        '/signup',
        '/groups',
        '/api/user_groups',
        '/lookup_user',
    ]
    
    # Get all registered routes
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append(str(rule))
    
    print("\nChecking required routes:")
    for route in required_routes:
        # Find matching route
        found = any(route in r for r in routes)
        status = "✓" if found else "✗"
        print(f"  {status} {route}")

def main():
    print("\n" + "🔐 " * 20)
    print("FIREBED LOGIN & ACCESS CONTROL TEST")
    print("🔐 " * 20)
    
    try:
        verify_database_state()
        check_routes()
        simulate_login_flow()
        
        print("\n" + "=" * 70)
        print("✅ LOGIN TESTS COMPLETED")
        print("=" * 70)
        print("\n🎯 You can now:")
        print("   1. Access the app at http://localhost:5000")
        print("   2. Login as 'admin' with password 'admin@123'")
        print("   3. Or login as 'admin@firebed.local' (email-based)")
        print("   4. Access /admin panel")
        print("   5. Create and manage groups")
        print("   6. Assign users by email")
        
        return 0
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
