#!/usr/bin/env python3
"""
Firebed Setup Assistant - Email & Firebase Configuration
Interactive setup for SMTP email and Firebase integration

Supported Email Providers:
- Gmail (smtp.gmail.com:587)
- Outlook.com/Hotmail (smtp-mail.outlook.com:587) 
- Office 365 (smtp.office365.com:587)
- Yahoo Mail (smtp.mail.yahoo.com:587)
- Custom SMTP servers

Features:
- SMTP configuration and testing
- Firebase integration setup
- Email template testing
- Comprehensive .env file generation
"""

import os
import getpass
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def test_smtp_connection(server, port, username, password):
    """Test SMTP connection with given settings"""
    try:
        with smtplib.SMTP(server, port) as smtp:
            smtp.starttls()
            smtp.login(username, password)
        return True, "Connection successful"
    except Exception as e:
        return False, str(e)

def get_smtp_settings():
    """Interactive SMTP configuration"""
    print("🔧 SMTP Configuration Setup")
    print("=" * 50)
    
    # Provider selection with correct Microsoft settings
    providers = {
        '1': {
            'name': 'Gmail', 
            'server': 'smtp.gmail.com', 
            'port': 587,
            'auth_note': 'Requires App Password (not regular password)'
        },
        '2': {
            'name': 'Outlook.com (Hotmail, Live.com)', 
            'server': 'smtp-mail.outlook.com', 
            'port': 587,
            'auth_note': 'REQUIRES App Password - Basic auth disabled by Microsoft'
        },
        '3': {
            'name': 'Office 365 (Business)', 
            'server': 'smtp.office365.com', 
            'port': 587,
            'auth_note': 'Use your Office 365 credentials'
        },
        '4': {
            'name': 'Yahoo Mail', 
            'server': 'smtp.mail.yahoo.com', 
            'port': 587,
            'auth_note': 'Requires App Password'
        },
        '5': {
            'name': 'Custom SMTP Server', 
            'server': '', 
            'port': 587,
            'auth_note': 'Enter your own SMTP settings'
        }
    }
    
    print("Select your email provider:")
    for key, provider in providers.items():
        print(f"  {key}. {provider['name']}")
        print(f"      Server: {provider['server'] or 'Custom'}")
        print(f"      Note: {provider['auth_note']}")
        print()
    
    choice = input("Enter choice (1-5): ").strip()
    
    if choice in providers:
        provider = providers[choice]
        if choice == '5':  # Custom
            print("\n📝 Custom SMTP Configuration")
            server = input("SMTP Server: ").strip()
            port = int(input("SMTP Port (default 587): ") or "587")
            print("\n💡 Common SMTP Settings:")
            print("  • Gmail: smtp.gmail.com:587")
            print("  • Outlook.com: smtp-mail.outlook.com:587")
            print("  • Office 365: smtp.office365.com:587")
            print("  • Yahoo: smtp.mail.yahoo.com:587")
        else:
            server = provider['server']
            port = provider['port']
            print(f"\n✅ Selected: {provider['name']}")
            print(f"   Server: {server}:{port}")
            print(f"   {provider['auth_note']}")
            
            # Provider-specific instructions
            if choice == '1':  # Gmail
                print("\n📋 Gmail Setup Instructions:")
                print("   1. Enable 2-Factor Authentication")
                print("   2. Go to Google Account > Security > App passwords")
                print("   3. Generate an app password for 'Mail'")
                print("   4. Use the app password (not your regular password)")
            elif choice == '2':  # Outlook.com
                print("\n📋 Outlook.com Setup Instructions (UPDATED 2024):")
                print("   ⚠️  Microsoft disabled basic authentication!")
                print("   1. Enable 2-Factor Authentication (REQUIRED)")
                print("   2. Go to account.microsoft.com > Security")
                print("   3. Navigate to 'Advanced security options'")
                print("   4. Generate App Password for 'Mail'")
                print("   5. Use App Password (NOT your regular password)")
                print("   Note: Regular passwords no longer work for SMTP")
            elif choice == '3':  # Office 365
                print("\n📋 Office 365 Setup Instructions:")
                print("   1. Use your Office 365 work/school account")
                print("   2. Contact IT admin if SMTP is disabled")
                print("   3. May require app password for security")
            elif choice == '4':  # Yahoo
                print("\n📋 Yahoo Mail Setup Instructions:")
                print("   1. Enable 2-step verification")
                print("   2. Generate app password in Account Security")
                print("   3. Use app password (not regular password)")
    else:
        print("Invalid choice, using Gmail defaults")
        server = 'smtp.gmail.com'
        port = 587
    
    # Get credentials with provider-specific prompts
    print("\n📧 Email Credentials")
    username = input("Email address: ").strip()
    
    if choice == '1':  # Gmail
        password = getpass.getpass("App Password (16 characters, no spaces): ")
    elif choice == '2':  # Outlook.com
        password = getpass.getpass("App Password (REQUIRED - regular password won't work): ")
    elif choice == '3':  # Office 365
        password = getpass.getpass("Office 365 Password: ")
    elif choice == '4':  # Yahoo
        password = getpass.getpass("Yahoo App Password: ")
    else:
        password = getpass.getpass("Password: ")
    
    return server, port, username, password

def setup_firebase_config():
    """Interactive Firebase configuration setup"""
    print("\n🔥 Firebase Configuration (Optional)")
    print("=" * 50)
    print("Firebase enables enhanced authentication and cloud storage.")
    
    if input("Configure Firebase? (y/N): ").lower() != 'y':
        return None
    
    firebase_config = {}
    
    # Check for existing firebase-key.json
    if os.path.exists('firebase-key.json'):
        print("✅ Found existing firebase-key.json")
        firebase_config['key_path'] = 'firebase-key.json'
    else:
        print("\n📋 Firebase Setup Instructions:")
        print("   1. Go to Firebase Console > Project Settings")
        print("   2. Navigate to 'Service accounts' tab")
        print("   3. Click 'Generate new private key'")
        print("   4. Save the JSON file as 'firebase-key.json'")
        
        key_path = input("\nFirebase key file path (default: firebase-key.json): ").strip()
        firebase_config['key_path'] = key_path or 'firebase-key.json'
        
        if not os.path.exists(firebase_config['key_path']):
            print(f"⚠️  Warning: {firebase_config['key_path']} not found")
            print("   You can add it later and restart the server")
    
    # Firebase project settings
    print("\n🔧 Firebase Project Configuration:")
    firebase_config['project_id'] = input("Project ID (optional): ").strip()
    firebase_config['database_url'] = input("Database URL (optional): ").strip()
    
    return firebase_config

def create_env_file(server, port, username, password, app_url, firebase_config=None):
    """Create .env file with SMTP and Firebase settings"""
    env_content = f"""# Firebed Configuration
# Generated by setup assistant on {os.popen('date').read().strip()}

# ========================================
# SMTP Email Configuration
# ========================================
SMTP_SERVER={server}
SMTP_PORT={port}
SMTP_USER={username}
SMTP_PASSWORD={password}
SENDER_EMAIL={username}

# ========================================
# Application Settings
# ========================================
APP_URL={app_url}
ADMIN_USER_ID=1

# Security (generate random values in production)
SECRET_KEY=dev-secret-key-change-in-production

# ========================================
# Database Configuration
# ========================================
# SQLite (default)
DATABASE_URL=sqlite:///firebed.db

# PostgreSQL (production)
# DATABASE_URL=postgresql://username:password@localhost:5432/firebed

"""
    
    # Add Firebase configuration if provided
    if firebase_config:
        env_content += """# ========================================
# Firebase Configuration
# ========================================
"""
        
        if firebase_config.get('key_path'):
            env_content += f"FIREBASE_ADMIN_KEY_PATH={firebase_config['key_path']}\n"
        
        if firebase_config.get('project_id'):
            env_content += f"FIREBASE_PROJECT_ID={firebase_config['project_id']}\n"
        
        if firebase_config.get('database_url'):
            env_content += f"FIREBASE_DATABASE_URL={firebase_config['database_url']}\n"
        
        env_content += """\n# Firebase Features (true/false)
FIREBASE_AUTH_ENABLED=true
FIREBASE_STORAGE_ENABLED=true
"""
    else:
        env_content += """# ========================================
# Firebase Configuration (Disabled)
# ========================================
# Uncomment and configure to enable Firebase
# FIREBASE_ADMIN_KEY_PATH=firebase-key.json
# FIREBASE_PROJECT_ID=your-project-id
# FIREBASE_DATABASE_URL=https://your-project.firebaseio.com
# FIREBASE_AUTH_ENABLED=false
# FIREBASE_STORAGE_ENABLED=false
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("\n✅ .env file created successfully!")
    if firebase_config:
        print("✅ Firebase configuration included")
    else:
        print("ℹ️  Firebase configuration skipped (can be added later)")

def send_test_email(server, port, username, password):
    """Send a test email to verify configuration"""
    test_email = input(f"\nSend test email to (default: {username}): ").strip() or username
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = '✅ Firebed Email Test - Success!'
        msg['From'] = username
        msg['To'] = test_email
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h1 style="margin: 0;">🎉 Firebed Email Test</h1>
                </div>
                
                <div style="background: white; padding: 20px; border: 1px solid #dee2e6; border-radius: 0 0 10px 10px;">
                    <h2 style="color: #28a745;">✅ Congratulations!</h2>
                    <p>Your Firebed email system is configured correctly and working!</p>
                    
                    <div style="background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 5px; margin: 20px 0;">
                        <h3 style="color: #0c5460; margin-top: 0;">📋 Configuration Summary:</h3>
                        <p style="margin: 5px 0;"><strong>SMTP Server:</strong> {server}:{port}</p>
                        <p style="margin: 5px 0;"><strong>Email Account:</strong> {username}</p>
                        <p style="margin: 5px 0;"><strong>Test Date:</strong> {os.popen('date').read().strip()}</p>
                    </div>
                    
                    <h3 style="color: #495057;">🚀 What's Next?</h3>
                    <ul style="color: #6c757d;">
                        <li>Start/restart your Firebed server</li>
                        <li>Users can now receive signup verification emails</li>
                        <li>Password reset emails will work</li>
                        <li>Admin panel email tab is ready to use</li>
                    </ul>
                    
                    <hr style="margin: 20px 0;">
                    <p style="text-align: center; color: #6c757d; font-size: 14px;">
                        This test email was sent by the Firebed Email Setup Assistant
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg.attach(MIMEText(html_body, 'html'))
        
        with smtplib.SMTP(server, port) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(username, test_email, msg.as_string())
        
        print(f"✅ Test email sent successfully to {test_email}!")
        return True
    
    except Exception as e:
        print(f"❌ Failed to send test email: {e}")
        return False

def main():
    print("🚀 Firebed Setup Assistant")
    print("=" * 60)
    print("Configure email & Firebase integration for Firebed")
    print("\n📧 Email Features:")
    print("   • User signup verification emails")
    print("   • Password reset emails") 
    print("   • Admin bulk email system")
    print("   • Professional email templates")
    print("\n🔥 Firebase Features (Optional):")
    print("   • Enhanced authentication")
    print("   • Cloud data synchronization")
    print("   • Real-time updates")
    print("   • Scalable storage")
    print()
    
    # Check if .env already exists
    if os.path.exists('.env'):
        response = input("⚠️  .env file already exists. Overwrite? (y/N): ")
        if response.lower() != 'y':
            print("Setup cancelled.")
            return
    
    try:
        # Get SMTP settings
        server, port, username, password = get_smtp_settings()
        
        # Test connection
        print(f"\n🔍 Testing SMTP connection to {server}:{port}...")
        success, message = test_smtp_connection(server, port, username, password)
        
        if not success:
            print(f"❌ SMTP Connection failed: {message}")
            
            # Specific error handling for common authentication issues
            if "5.7.139" in str(message) or "basic authentication is disabled" in str(message).lower():
                print("\n🚨 MICROSOFT OUTLOOK ERROR DETECTED:")
                print("   Microsoft has disabled basic authentication (username/password)")
                print("   You MUST use an App Password instead of your regular password")
                print("\n📋 Required Steps:")
                print("   1. Go to account.microsoft.com > Security")
                print("   2. Enable 2-Factor Authentication")
                print("   3. Navigate to 'Advanced security options'")
                print("   4. Generate App Password for 'Mail'")
                print("   5. Use the App Password (16 characters, no spaces)")
                print("\n⚠️  Regular Microsoft passwords no longer work for SMTP!")
            else:
                print("\n💡 General Troubleshooting Tips:")
                print("  • Gmail: Use App Password, not regular password")
                print("  • Outlook.com: MUST use App Password (basic auth disabled)")
                print("  • Office 365: May need IT admin to enable SMTP")
                print("  • Yahoo: Requires App Password with 2-step verification")
                print("  • Check server name and port number")
            
            retry = input("\nRetry with different settings? (y/N): ")
            if retry.lower() == 'y':
                return main()  # Restart the setup
            else:
                return False
        
        print("✅ SMTP connection successful!")
        
        # Get app URL
        print(f"\n🌐 Application URL Configuration")
        print("This URL is used in email links for verification and password reset.")
        app_url = input("App URL (default: http://localhost:5000): ").strip() or "http://localhost:5000"
        
        # Firebase configuration
        firebase_config = setup_firebase_config()
        
        # Create .env file
        create_env_file(server, port, username, password, app_url, firebase_config)
        
        # Send test email
        print(f"\n📧 Email Testing")
        if input("Send test email to verify configuration? (Y/n): ").lower() != 'n':
            if send_test_email(server, port, username, password):
                print("✅ Email system fully operational!")
            else:
                print("⚠️  SMTP works but test email failed - check recipient address")
        
        # Final summary
        print("\n" + "=" * 60)
        print("🎉 Firebed Email & Firebase Setup Complete!")
        print("=" * 60)
        
        print("\n📧 Email Features Configured:")
        print(f"   ✅ SMTP Server: {server}:{port}")
        print(f"   ✅ Sender Email: {username}")
        print("   ✅ User signup verification emails")
        print("   ✅ Password reset emails")
        print("   ✅ Admin bulk email system")
        
        if firebase_config:
            print("\n🔥 Firebase Features Configured:")
            print("   ✅ Enhanced authentication")
            print("   ✅ Cloud data storage")
            print("   ✅ Real-time synchronization")
        
        print("\n📋 Next Steps:")
        print("   1. Start/restart Firebed server: python app.py")
        print("   2. Test user signup with email verification")
        print("   3. Try password reset functionality")
        print("   4. Use Admin Panel > Email tab for bulk emails")
        print("   5. Run comprehensive test: python test_email_setup.py")
        
        if firebase_config and not os.path.exists(firebase_config.get('key_path', '')):
            print("\n⚠️  Firebase Key File Missing:")
            print(f"   Add {firebase_config.get('key_path')} and restart server")
        
        return True
        
    except KeyboardInterrupt:
        print("\n\n🚫 Setup cancelled by user")
        return False
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)