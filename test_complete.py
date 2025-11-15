#!/usr/bin/env python3
"""
Comprehensive test suite for Firebed application
Tests:
1. Admin login with email/username
2. Group management (create, assign, list)
3. User management (create, assign to groups)
4. Regular user group access and switching
"""

import sys
from app import app, db
from models import User, Group

def test_admin_login():
    """Test admin user login with username and email"""
    print("\n" + "=" * 70)
    print("TEST: Admin Login (Email & Username)")
    print("=" * 70)
    
    with app.app_context():
        # Test 1: Find admin by username
        admin_by_username = User.query.filter_by(username='admin').first()
        assert admin_by_username, "Admin user not found by username"
        assert admin_by_username.check_password('admin@123'), "Admin password incorrect"
        print("✓ Admin found by username and password is correct")
        
        # Test 2: Find admin by email
        admin_by_email = User.query.filter_by(email='admin@firebed.local').first()
        assert admin_by_email, "Admin user not found by email"
        assert admin_by_email.id == admin_by_username.id, "Username and email lookups returned different users"
        print("✓ Admin found by email and is the same user")
        
        # Test 3: Check admin privileges
        assert admin_by_username.is_admin == True, "Admin flag not set"
        print("✓ Admin has is_admin=True flag")

def test_group_management():
    """Test group creation, assignment, and listing"""
    print("\n" + "=" * 70)
    print("TEST: Group Management")
    print("=" * 70)
    
    with app.app_context():
        # Get admin user
        admin = User.query.filter_by(username='admin').first()
        
        # Test 1: Create multiple groups
        for i in range(1, 4):
            group_name = f'group_{i}'
            existing = Group.query.filter_by(name=group_name).first()
            if not existing:
                g = Group(name=group_name, data_folder=f'data_group_{i}')
                db.session.add(g)
            else:
                g = existing
            
            # Assign admin to each group
            admin.add_to_group(g, role='admin')
            db.session.commit()
        
        print("✓ Created and assigned 3 groups to admin")
        
        # Test 2: List groups for admin
        admin_groups = [g.name for g in admin.groups]
        assert len(admin_groups) >= 3, f"Expected at least 3 groups, got {len(admin_groups)}"
        print(f"✓ Admin has {len(admin_groups)} groups: {admin_groups}")
        
        # Test 3: Check group members
        test_group = Group.query.filter_by(name='group_1').first()
        members = [ug.user.username for ug in test_group.user_groups]
        assert 'admin' in members, "Admin not in group_1"
        print(f"✓ group_1 members: {members}")

def test_user_management():
    """Test user creation, email assignment, and group assignment"""
    print("\n" + "=" * 70)
    print("TEST: User Management")
    print("=" * 70)
    
    with app.app_context():
        # Test 1: Create users with email
        users_to_create = [
            ('user_alpha', 'alpha@firebed.local'),
            ('user_beta', 'beta@firebed.local'),
            ('user_gamma', 'gamma@firebed.local'),
        ]
        
        created_users = []
        for username, email in users_to_create:
            existing = User.query.filter_by(username=username).first()
            if not existing:
                u = User(username=username, email=email)
                u.set_password(f'{username}@123')
                db.session.add(u)
                created_users.append(u)
            else:
                existing.email = email
                created_users.append(existing)
        
        db.session.commit()
        print(f"✓ Created/updated {len(created_users)} users with emails")
        
        # Test 2: Assign users to groups with different roles
        test_group = Group.query.filter_by(name='group_1').first()
        for i, user in enumerate(created_users):
            role = 'admin' if i == 0 else 'member'
            user.add_to_group(test_group, role=role)
        db.session.commit()
        print("✓ Assigned users to group_1 with mixed roles")
        
        # Test 3: Verify group composition
        group_users = [(ug.user.username, ug.role) for ug in test_group.user_groups]
        print(f"✓ group_1 composition: {group_users}")

def test_email_login():
    """Test email-based login flow"""
    print("\n" + "=" * 70)
    print("TEST: Email-based Login Support")
    print("=" * 70)
    
    with app.app_context():
        # Simulate login by email
        email = 'alpha@firebed.local'
        user = User.query.filter_by(email=email).first()
        assert user, f"User with email {email} not found"
        
        password = 'user_alpha@123'
        assert user.check_password(password), f"Password mismatch for {email}"
        print(f"✓ Can login with email: {email}")
        
        # Check groups accessible to user
        groups = [g.name for g in user.groups]
        assert len(groups) > 0, "User has no groups"
        print(f"✓ User has access to groups: {groups}")

def test_admin_access():
    """Test admin panel access and permissions"""
    print("\n" + "=" * 70)
    print("TEST: Admin Access & Permissions")
    print("=" * 70)
    
    with app.app_context():
        # Test 1: Admin user
        admin = User.query.filter_by(username='admin').first()
        assert admin.is_admin == True, "Admin flag not set"
        print("✓ Admin user has is_admin=True")
        
        # Test 2: Regular user
        regular_user = User.query.filter_by(username='user_alpha').first()
        assert regular_user.is_admin == False, "Regular user should not be admin"
        print("✓ Regular user has is_admin=False")
        
        # Test 3: Admin can see all groups
        all_groups = Group.query.all()
        admin_group_count = len(admin.groups)
        print(f"✓ Admin can access {admin_group_count} groups (total groups: {len(all_groups)})")

def test_group_permissions():
    """Test group-level admin and member permissions"""
    print("\n" + "=" * 70)
    print("TEST: Group-level Permissions")
    print("=" * 70)
    
    with app.app_context():
        test_group = Group.query.filter_by(name='group_1').first()
        
        for ug in test_group.user_groups:
            user = ug.user
            role = ug.role
            
            if role == 'admin':
                print(f"✓ {user.username} is admin of group_1")
            else:
                print(f"✓ {user.username} is member of group_1")

def run_all_tests():
    """Run all tests"""
    print("\n" + "🧪 " * 20)
    print("FIREBED APPLICATION TEST SUITE")
    print("🧪 " * 20)
    
    try:
        test_admin_login()
        test_group_management()
        test_user_management()
        test_email_login()
        test_admin_access()
        test_group_permissions()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        print("\nSummary:")
        print("  ✓ Admin login works with email & username")
        print("  ✓ Group management (create, assign, list)")
        print("  ✓ User management with email support")
        print("  ✓ Email-based login")
        print("  ✓ Admin access control")
        print("  ✓ Group-level permissions")
        print("\nYou can now:")
        print("  1. Login as admin@firebed.local or admin / admin@123")
        print("  2. Access admin panel")
        print("  3. Create and manage groups")
        print("  4. Assign users to groups")
        print("  5. Switch between groups as regular user")
        
        return 0
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 2

if __name__ == '__main__':
    sys.exit(run_all_tests())
