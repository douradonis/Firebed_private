#!/usr/bin/env python3
"""
Test Mailpit Email Integration

This script tests the Mailpit email sending functionality.
Mailpit must be running locally for these tests to pass.

To start Mailpit:
- Mac: brew services start mailpit
- Docker: docker run -d --name mailpit -p 8025:8025 -p 1025:1025 axllent/mailpit
- Binary: ./mailpit

Then access the web UI at http://localhost:8025
"""

import os
import sys

# Set environment variables for testing
os.environ['EMAIL_PROVIDER'] = 'mailpit'
os.environ['MAILPIT_API_URL'] = 'http://localhost:8025'
os.environ['SENDER_EMAIL'] = 'test@example.com'

from email_utils import send_mailpit_email, get_email_provider, MAILPIT_API_URL


def test_mailpit_provider_detection():
    """Test that Mailpit provider is correctly detected"""
    print("\n" + "=" * 60)
    print("TEST 1: Mailpit Provider Detection")
    print("=" * 60)
    
    provider = get_email_provider()
    print(f"Current email provider: {provider}")
    
    if provider == 'mailpit':
        print("✅ PASS: Mailpit provider detected correctly")
        return True
    else:
        print(f"❌ FAIL: Expected 'mailpit', got '{provider}'")
        return False


def test_mailpit_configuration():
    """Test Mailpit configuration"""
    print("\n" + "=" * 60)
    print("TEST 2: Mailpit Configuration")
    print("=" * 60)
    
    print(f"MAILPIT_API_URL: {MAILPIT_API_URL}")
    
    if MAILPIT_API_URL:
        print("✅ PASS: Mailpit API URL is configured")
        return True
    else:
        print("❌ FAIL: Mailpit API URL is not configured")
        return False


def test_mailpit_email_sending():
    """Test sending an email via Mailpit"""
    print("\n" + "=" * 60)
    print("TEST 3: Mailpit Email Sending")
    print("=" * 60)
    
    test_email = "recipient@example.com"
    subject = "Test Email from Mailpit Integration"
    html_body = """
    <html>
        <body>
            <h1>Mailpit Test Email</h1>
            <p>This is a test email sent via the Mailpit integration.</p>
            <p>If you see this in the Mailpit web UI at <a href="http://localhost:8025">http://localhost:8025</a>, the integration is working!</p>
        </body>
    </html>
    """
    text_body = "Mailpit Test Email\n\nThis is a test email sent via the Mailpit integration."
    
    print(f"Sending test email to: {test_email}")
    print(f"Subject: {subject}")
    
    try:
        result = send_mailpit_email(test_email, subject, html_body, text_body)
        
        if result:
            print("✅ PASS: Email sent successfully via Mailpit")
            print(f"📧 Check your Mailpit web UI at {MAILPIT_API_URL} to see the email")
            return True
        else:
            print("❌ FAIL: Email sending failed")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        return False


def test_mailpit_with_send_email():
    """Test sending via the main send_email function"""
    print("\n" + "=" * 60)
    print("TEST 4: Main send_email() Function with Mailpit")
    print("=" * 60)
    
    from email_utils import send_email
    
    test_email = "user@example.com"
    subject = "Test via send_email() - Mailpit"
    html_body = """
    <html>
        <body>
            <h2>Testing send_email() Function</h2>
            <p>This email was sent using the main send_email() function with Mailpit provider.</p>
        </body>
    </html>
    """
    
    print(f"Sending email via send_email() to: {test_email}")
    
    try:
        result = send_email(test_email, subject, html_body)
        
        if result:
            print("✅ PASS: Email routed to Mailpit successfully")
            print(f"📧 Check Mailpit web UI at {MAILPIT_API_URL}")
            return True
        else:
            print("❌ FAIL: Email sending failed")
            return False
            
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("MAILPIT EMAIL INTEGRATION TESTS")
    print("=" * 60)
    print("\n⚠️  PREREQUISITE: Mailpit must be running on http://localhost:8025")
    print("   Start Mailpit with: brew services start mailpit")
    print("   Or with Docker: docker run -d -p 8025:8025 -p 1025:1025 axllent/mailpit")
    
    results = []
    
    # Run tests
    results.append(("Provider Detection", test_mailpit_provider_detection()))
    results.append(("Configuration Check", test_mailpit_configuration()))
    results.append(("Direct Email Sending", test_mailpit_email_sending()))
    results.append(("Main send_email() Function", test_mailpit_with_send_email()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        print(f"📧 View captured emails at: {MAILPIT_API_URL}")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        print("\nTroubleshooting:")
        print("1. Make sure Mailpit is running: brew services list | grep mailpit")
        print("2. Check if port 8025 is accessible: curl http://localhost:8025")
        print("3. Verify MAILPIT_API_URL is set correctly")
        return 1


if __name__ == "__main__":
    sys.exit(main())
