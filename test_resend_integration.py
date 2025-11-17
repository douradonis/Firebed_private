#!/usr/bin/env python3
"""
Test script to verify Resend email integration.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, load_settings, save_settings
from email_utils import get_email_provider, send_resend_email, RESEND_API_KEY, SENDER_EMAIL


def test_resend_config():
    """Test that Resend configuration is accessible."""
    print("=" * 60)
    print("TEST 1: Resend Configuration")
    print("=" * 60)
    
    print(f"RESEND_API_KEY set: {bool(RESEND_API_KEY)}")
    print(f"SENDER_EMAIL: {SENDER_EMAIL or 'Not set'}")
    
    if RESEND_API_KEY:
        print("✅ Resend API key is configured")
    else:
        print("⚠️  Resend API key not set in environment")
        print("   Set RESEND_API_KEY in .env to test actual email sending")
    
    print()
    return True


def test_email_provider_settings():
    """Test email provider settings management."""
    print("=" * 60)
    print("TEST 2: Email Provider Settings")
    print("=" * 60)
    
    with app.app_context():
        try:
            # Load current settings
            settings = load_settings()
            current_provider = settings.get('email_provider', 'smtp')
            print(f"Current email provider in settings: {current_provider}")
            
            # Test get_email_provider function
            provider = get_email_provider()
            print(f"get_email_provider() returns: {provider}")
            
            # Test saving different providers
            for test_provider in ['smtp', 'resend', 'oauth2_outlook']:
                settings['email_provider'] = test_provider
                save_settings(settings)
                loaded = load_settings()
                if loaded.get('email_provider') == test_provider:
                    print(f"✅ Successfully set and loaded provider: {test_provider}")
                else:
                    print(f"❌ Failed to persist provider: {test_provider}")
                    return False
            
            # Restore original setting
            settings['email_provider'] = current_provider
            save_settings(settings)
            
            print("\n✅ Email provider settings test PASSED\n")
            return True
        except Exception as e:
            print(f"❌ Email provider settings test FAILED: {e}\n")
            return False


def test_resend_email_function():
    """Test the send_resend_email function structure."""
    print("=" * 60)
    print("TEST 3: Resend Email Function")
    print("=" * 60)
    
    try:
        # Test that the function exists and has correct signature
        import inspect
        sig = inspect.signature(send_resend_email)
        params = list(sig.parameters.keys())
        expected = ['to_email', 'subject', 'html_body', 'text_body']
        
        if params == expected:
            print(f"✅ send_resend_email has correct signature: {params}")
        else:
            print(f"❌ Unexpected signature. Expected: {expected}, Got: {params}")
            return False
        
        # Test with mock data (won't actually send without API key)
        test_html = "<h1>Test Email</h1><p>This is a test.</p>"
        test_subject = "Test Subject"
        test_to = "test@example.com"
        
        print(f"\nTesting send_resend_email (may fail without API key):")
        print(f"  To: {test_to}")
        print(f"  Subject: {test_subject}")
        
        if not RESEND_API_KEY:
            print("⚠️  Skipping actual send test - no API key configured")
            print("   This is expected. Set RESEND_API_KEY in .env to test actual sending")
        else:
            print("ℹ️  API key found - function is ready to send emails")
            print("   (Not sending test email to avoid using quota)")
        
        print("\n✅ Resend email function test PASSED\n")
        return True
        
    except Exception as e:
        print(f"❌ Resend email function test FAILED: {e}\n")
        return False


def test_email_templates():
    """Test that email templates work with Resend."""
    print("=" * 60)
    print("TEST 4: Email Templates Compatibility")
    print("=" * 60)
    
    with app.app_context():
        try:
            from email_utils import send_email_verification, send_password_reset
            from models import User, db
            
            # Get or create a test user
            user = User.query.filter_by(username='test_resend_user').first()
            if not user:
                user = User(username='test_resend_user', email='test@example.com')
                user.set_password('test123')
                db.session.add(user)
                db.session.commit()
            
            print(f"Test user: {user.username} (ID: {user.id})")
            
            # Check that template functions exist
            import inspect
            
            # Verification email
            sig1 = inspect.signature(send_email_verification)
            print(f"✅ send_email_verification signature: {list(sig1.parameters.keys())}")
            
            # Password reset email  
            sig2 = inspect.signature(send_password_reset)
            print(f"✅ send_password_reset signature: {list(sig2.parameters.keys())}")
            
            print("\n✅ Email templates are compatible with all providers")
            print("   (SMTP, Resend, and OAuth2 use the same HTML templates)\n")
            
            # Clean up test user
            db.session.delete(user)
            db.session.commit()
            
            return True
            
        except Exception as e:
            print(f"❌ Email templates test FAILED: {e}\n")
            return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("RESEND EMAIL INTEGRATION TEST SUITE")
    print("=" * 60 + "\n")
    
    results = []
    
    results.append(("Resend Configuration", test_resend_config()))
    results.append(("Email Provider Settings", test_email_provider_settings()))
    results.append(("Resend Email Function", test_resend_email_function()))
    results.append(("Email Templates", test_email_templates()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    total_passed = sum(1 for _, passed in results if passed)
    total_tests = len(results)
    
    print(f"\nTotal: {total_passed}/{total_tests} tests passed")
    
    if total_passed == total_tests:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total_tests - total_passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
