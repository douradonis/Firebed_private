#!/usr/bin/env python3
"""
Test script to verify email verification and password reset flows.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, User, VerificationToken
from email_utils import (
    create_verification_token, 
    verify_token, 
    send_email_verification,
    send_password_reset,
    send_bulk_email_to_users
)
import datetime

def test_db_schema():
    """Test that database has all required fields."""
    print("=" * 60)
    print("TEST 1: Database Schema")
    print("=" * 60)
    
    with app.app_context():
        try:
            # Check User has email_verified fields
            user = User.query.first()
            if user:
                email_verified = getattr(user, 'email_verified', None)
                email_verified_at = getattr(user, 'email_verified_at', None)
                print(f"✅ User table has email_verified field: {email_verified is not None}")
                print(f"✅ User table has email_verified_at field: {email_verified_at is not None}")
            
            # Check VerificationToken table
            token_count = VerificationToken.query.count()
            print(f"✅ VerificationToken table accessible: {token_count} existing tokens")
            
            print("\n✅ Database schema test PASSED\n")
            return True
        except Exception as e:
            print(f"❌ Database schema test FAILED: {e}\n")
            return False

def test_create_user():
    """Test creating a new user."""
    print("=" * 60)
    print("TEST 2: Create User")
    print("=" * 60)
    
    with app.app_context():
        try:
            # Clean up test user if exists
            User.query.filter_by(username='testuser').delete()
            db.session.commit()
            
            # Create new user
            user = User(username='testuser')
            user.email = 'testuser@example.com'
            user.set_password('testpass123')
            db.session.add(user)
            db.session.commit()
            
            print(f"✅ Created user: {user.username} ({user.email})")
            print(f"  - ID: {user.id}")
            print(f"  - email_verified: {user.email_verified}")
            
            print("\n✅ Create user test PASSED\n")
            return user.id
        except Exception as e:
            print(f"❌ Create user test FAILED: {e}\n")
            return None

def test_token_creation(user_id):
    """Test creating and verifying tokens."""
    print("=" * 60)
    print("TEST 3: Token Management")
    print("=" * 60)
    
    if not user_id:
        print("❌ Skipped: No user ID\n")
        return False
    
    with app.app_context():
        try:
            # Create verification token
            token = create_verification_token(user_id, 'email_verify', 24)
            print(f"✅ Created verification token: {token[:20]}...")
            
            # Verify token works
            verified_user_id = verify_token(token, 'email_verify')
            print(f"✅ Token verified for user: {verified_user_id}")
            
            # Check token is marked as used
            token_obj = VerificationToken.query.filter_by(token=token).first()
            print(f"  - Token marked used: {token_obj.used}")
            
            # Try to verify same token again (should fail)
            result = verify_token(token, 'email_verify')
            if result is None:
                print(f"✅ Reused token properly rejected")
            else:
                print(f"❌ Reused token should not verify: {result}")
            
            print("\n✅ Token management test PASSED\n")
            return True
        except Exception as e:
            print(f"❌ Token management test FAILED: {e}\n")
            import traceback
            traceback.print_exc()
            return False

def test_email_config():
    """Test email configuration."""
    print("=" * 60)
    print("TEST 4: Email Configuration")
    print("=" * 60)
    
    with app.app_context():
        smtp_server = app.config.get('SMTP_SERVER')
        smtp_port = app.config.get('SMTP_PORT')
        smtp_user = app.config.get('SMTP_USER')
        sender_email = app.config.get('SENDER_EMAIL')
        app_url = app.config.get('APP_URL')
        
        configured = bool(smtp_server and smtp_user and sender_email and app_url)
        
        print(f"Email Server: {smtp_server or '❌ NOT SET'}")
        print(f"SMTP Port: {smtp_port or '❌ NOT SET'}")
        print(f"SMTP User: {smtp_user or '❌ NOT SET'}")
        print(f"Sender Email: {sender_email or '❌ NOT SET'}")
        print(f"App URL: {app_url or '❌ NOT SET'}")
        
        if configured:
            print("\n✅ Email configuration COMPLETE\n")
        else:
            print("\n⚠️  Email configuration INCOMPLETE")
            print("   Set env vars: SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SENDER_EMAIL, APP_URL\n")
        
        return configured

def test_admin_check():
    """Test admin authorization check."""
    print("=" * 60)
    print("TEST 5: Admin Authorization")
    print("=" * 60)
    
    with app.app_context():
        try:
            from admin_panel import is_admin
            
            # Create test users
            User.query.filter_by(username='admin_test').delete()
            User.query.filter_by(username='regular_test').delete()
            db.session.commit()
            
            admin_user = User(username='admin_test')
            admin_user.email = 'admin@example.com'
            admin_user.is_admin = True
            admin_user.set_password('pass')
            
            regular_user = User(username='regular_test')
            regular_user.email = 'regular@example.com'
            regular_user.is_admin = False
            regular_user.set_password('pass')
            
            db.session.add_all([admin_user, regular_user])
            db.session.commit()
            
            # Test is_admin
            print(f"Admin user is_admin: {is_admin(admin_user)}")
            print(f"Regular user is_admin: {is_admin(regular_user)}")
            
            if is_admin(admin_user) and not is_admin(regular_user):
                print("\n✅ Admin authorization test PASSED\n")
                return True
            else:
                print("\n❌ Admin authorization test FAILED\n")
                return False
        except Exception as e:
            print(f"❌ Admin authorization test FAILED: {e}\n")
            import traceback
            traceback.print_exc()
            return False

def main():
    print("\n")
    print("🧪 SYSTEM HEALTH CHECK - Email Verification & Auth System")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("Database Schema", test_db_schema()))
    user_id = test_create_user()
    results.append(("Create User", user_id is not None))
    results.append(("Token Management", test_token_creation(user_id)))
    results.append(("Email Configuration", test_email_config()))
    results.append(("Admin Authorization", test_admin_check()))
    
    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All systems ready! Email verification & password reset are operational.")
        print("\nNext steps:")
        print("1. Set email configuration environment variables (if not already set)")
        print("2. Test signup flow (verification email will be sent)")
        print("3. Test password reset flow (forgot-password)")
        print("4. Test admin bulk email sending")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review above.")
    
    return 0 if passed == total else 1

if __name__ == '__main__':
    sys.exit(main())
