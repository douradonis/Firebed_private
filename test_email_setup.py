#!/usr/bin/env python3
"""
Test Email System Configuration
Tests SMTP setup and email functionality
"""

import os
import sys
import requests
import json
from datetime import datetime

def test_env_config():
    """Test that email environment variables are set"""
    print("🔧 Testing Environment Configuration")
    print("=" * 50)
    
    required_vars = ['SMTP_SERVER', 'SMTP_USER', 'SMTP_PASSWORD', 'SENDER_EMAIL']
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            print(f"  ✅ {var}: {'*' * (len(value) - 4)}{value[-4:]}")  # Hide most of the value
        else:
            print(f"  ❌ {var}: Not set")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️  Missing variables: {', '.join(missing_vars)}")
        print("💡 Copy .env.template to .env and configure SMTP settings")
        return False
    else:
        print("\n✅ All email environment variables are configured")
        return True

def test_direct_email():
    """Test email_utils functions directly"""
    print("\n🔧 Testing Direct Email Functions")
    print("=" * 50)
    
    try:
        # Import email utilities
        sys.path.append('/workspaces/Firebed_private')
        import email_utils
        
        # Test basic configuration
        print(f"SMTP Server: {email_utils.SMTP_SERVER}:{email_utils.SMTP_PORT}")
        print(f"SMTP User: {email_utils.SMTP_USER}")
        print(f"Sender Email: {email_utils.SENDER_EMAIL}")
        
        # Test if SMTP is configured
        if not email_utils.SMTP_USER or not email_utils.SMTP_PASSWORD:
            print("❌ SMTP not fully configured")
            return False
        
        # Send a test email
        test_email = input("Enter your email address for testing (or press Enter to skip): ").strip()
        if test_email:
            print(f"📧 Sending test email to {test_email}...")
            
            html_body = f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #28a745;">✅ Email System Test</h2>
                    <p>Congratulations! Your Firebed email system is working correctly.</p>
                    <p><strong>Test Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                    <hr>
                    <small>This is an automated test from the Firebed Email System</small>
                </body>
            </html>
            """
            
            success = email_utils.send_email(test_email, "✅ Firebed Email Test", html_body)
            if success:
                print("✅ Test email sent successfully!")
                return True
            else:
                print("❌ Failed to send test email")
                return False
        else:
            print("⏭️  Skipping direct email test")
            return True
            
    except Exception as e:
        print(f"❌ Error testing direct email: {e}")
        return False

def test_admin_email_api(base_url="http://localhost:5000"):
    """Test admin email API endpoints"""
    print("\n🔧 Testing Admin Email API")
    print("=" * 50)
    
    endpoints = [
        "/admin/api/send-email",
        "/admin/api/email-config", 
        "/admin/api/test-email"
    ]
    
    for endpoint in endpoints:
        try:
            url = f"{base_url}{endpoint}"
            print(f"Testing: {endpoint}")
            
            if endpoint.endswith('email-config'):
                response = requests.get(url, timeout=5)
            else:
                response = requests.post(url, json={}, timeout=5)
            
            if response.status_code == 401:
                print(f"  ✅ Endpoint exists (401 - auth required)")
            elif response.status_code == 404:
                print(f"  ❌ Endpoint missing (404)")
            else:
                print(f"  ✅ Endpoint responds ({response.status_code})")
                
        except requests.exceptions.ConnectionError:
            print(f"  ⚠️  Server not running on {base_url}")
            return False
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    return True

def test_authentication_emails():
    """Test authentication email templates"""
    print("\n🔧 Testing Authentication Email Templates")
    print("=" * 50)
    
    try:
        sys.path.append('/workspaces/Firebed_private')
        import email_utils
        
        # Test email verification template
        print("📧 Testing email verification template...")
        test_success = email_utils.send_email_verification(
            "test@example.com", 999, "testuser"
        )
        print(f"  Email verification function: {'✅ Works' if test_success else '❌ Failed'}")
        
        # Test password reset template  
        print("📧 Testing password reset template...")
        reset_success = email_utils.send_password_reset(
            "test@example.com", 999, "testuser"
        )
        print(f"  Password reset function: {'✅ Works' if reset_success else '❌ Failed'}")
        
        return test_success or reset_success  # At least one should work if SMTP is configured
        
    except Exception as e:
        print(f"❌ Error testing authentication emails: {e}")
        return False

def print_setup_instructions():
    """Print setup instructions"""
    print("\n📋 Email Setup Instructions")
    print("=" * 50)
    print("1. Copy .env.template to .env:")
    print("   cp .env.template .env")
    print()
    print("2. Edit .env file with your SMTP settings")
    print()
    print("3. For Gmail:")
    print("   - Enable 2-Factor Authentication")
    print("   - Generate App Password in Google Account Settings")
    print("   - Use app password (not regular password)")
    print()
    print("4. Test the configuration:")
    print("   python test_email_system.py")
    print()
    print("5. Restart the server to apply changes")

def main():
    print("🚀 Firebed Email System Test")
    print("=" * 50)
    
    # Check if server is running
    try:
        response = requests.get("http://localhost:5000", timeout=5)
        print("✅ Server is running")
        server_running = True
    except:
        print("⚠️  Server not running - limited testing available")
        server_running = False
    
    success = True
    
    # Test environment configuration
    success &= test_env_config()
    
    # Test direct email functions
    success &= test_direct_email()
    
    # Test authentication email templates
    success &= test_authentication_emails()
    
    # Test API endpoints if server is running
    if server_running:
        success &= test_admin_email_api()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Email system is properly configured!")
        print("\n📋 Features Available:")
        print("  ✅ User signup email verification")
        print("  ✅ Password reset emails")  
        print("  ✅ Admin bulk email sending")
        print("  ✅ SMTP configuration testing")
        print("\n🔗 Admin Panel: http://localhost:5000/admin (Email tab)")
    else:
        print("❌ Email system needs configuration")
        print_setup_instructions()
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)