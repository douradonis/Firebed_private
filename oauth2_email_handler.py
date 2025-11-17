#!/usr/bin/env python3
"""
Microsoft OAuth2 Email Handler για Firebed
Αποστολή emails μέσω Microsoft Graph API με OAuth2
"""

import json
import requests
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

class OutlookOAuth2EmailSender:
    def __init__(self, credentials_file='outlook_oauth2_credentials.json'):
        self.credentials_file = credentials_file
        self.credentials = None
        self.load_credentials()
    
    def load_credentials(self):
        """Load OAuth2 credentials from file"""
        try:
            with open(self.credentials_file, 'r') as f:
                self.credentials = json.load(f)
        except FileNotFoundError:
            raise Exception(f"OAuth2 credentials file not found: {self.credentials_file}")
        except json.JSONDecodeError:
            raise Exception("Invalid JSON in credentials file")
    
    def is_token_expired(self):
        """Check if access token is expired"""
        if not self.credentials.get('expires_at'):
            return True
        
        expires_at = datetime.fromisoformat(self.credentials['expires_at'])
        # Consider token expired 5 minutes before actual expiry
        return datetime.now() >= (expires_at - timedelta(minutes=5))
    
    def refresh_access_token(self):
        """Refresh the access token using refresh token"""
        if not self.credentials.get('refresh_token'):
            raise Exception("No refresh token available")
        
        data = {
            'client_id': self.credentials['client_id'],
            'client_secret': self.credentials['client_secret'],
            'refresh_token': self.credentials['refresh_token'],
            'grant_type': 'refresh_token',
            'scope': ' '.join(self.credentials['scopes'])
        }
        
        try:
            response = requests.post(self.credentials['token_url'], data=data)
            response.raise_for_status()
            token_data = response.json()
            
            # Update credentials
            self.credentials['access_token'] = token_data['access_token']
            if 'refresh_token' in token_data:
                self.credentials['refresh_token'] = token_data['refresh_token']
            
            expires_in = token_data.get('expires_in', 3600)
            self.credentials['expires_at'] = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
            
            # Save updated credentials
            with open(self.credentials_file, 'w') as f:
                json.dump(self.credentials, f, indent=2)
            
            print("✅ Access token refreshed successfully")
            
        except Exception as e:
            raise Exception(f"Token refresh failed: {e}")
    
    def get_valid_access_token(self):
        """Get a valid access token, refreshing if necessary"""
        if self.is_token_expired():
            print("🔄 Access token expired, refreshing...")
            self.refresh_access_token()
        
        return self.credentials['access_token']
    
    def send_email(self, to_email, subject, body, body_html=None):
        """Send email using Microsoft Graph API"""
        access_token = self.get_valid_access_token()
        
        # Microsoft Graph API endpoint
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Prepare email data
        email_data = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML" if body_html else "Text",
                    "content": body_html if body_html else body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ]
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=email_data)
            response.raise_for_status()
            return True
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Token might be invalid, try refresh once
                print("🔄 Token invalid, attempting refresh...")
                self.refresh_access_token()
                headers['Authorization'] = f'Bearer {self.get_valid_access_token()}'
                
                response = requests.post(url, headers=headers, json=email_data)
                response.raise_for_status()
                return True
            else:
                raise Exception(f"Email send failed: {e.response.text}")
        
        except Exception as e:
            raise Exception(f"Email send error: {e}")
    
    def test_connection(self):
        """Test OAuth2 connection and permissions"""
        try:
            access_token = self.get_valid_access_token()
            
            # Test by getting user profile
            url = "https://graph.microsoft.com/v1.0/me"
            headers = {'Authorization': f'Bearer {access_token}'}
            
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            user_data = response.json()
            email = user_data.get('mail') or user_data.get('userPrincipalName')
            
            print(f"✅ OAuth2 connection successful")
            print(f"   User: {user_data.get('displayName', 'Unknown')}")
            print(f"   Email: {email}")
            
            return True, f"Connected as {email}"
            
        except Exception as e:
            return False, str(e)

# Integration function for Firebed
def send_oauth2_email(to_email, subject, body, body_html=None):
    """
    Send email using OAuth2 - to be integrated into Firebed
    """
    try:
        sender = OutlookOAuth2EmailSender()
        return sender.send_email(to_email, subject, body, body_html)
    except Exception as e:
        print(f"OAuth2 email send failed: {e}")
        return False

# Test function
def test_oauth2_email():
    """Test OAuth2 email functionality"""
    print("🧪 Testing OAuth2 Email System")
    print("=" * 40)
    
    try:
        sender = OutlookOAuth2EmailSender()
        
        # Test connection
        success, message = sender.test_connection()
        if not success:
            print(f"❌ Connection test failed: {message}")
            return False
        
        # Test email send
        test_email = input("Enter email address for test (or press Enter to skip): ").strip()
        if test_email:
            print(f"\n📧 Sending test email to {test_email}...")
            
            subject = "Firebed OAuth2 Test Email"
            body = f"""
🎉 Συγχαρητήρια! Το OAuth2 Email System δουλεύει!

Αυτό είναι test email από το Firebed OAuth2 setup.
Το Microsoft Graph API λειτουργεί σωστά.

Χρόνος: {datetime.now().isoformat()}
Μέθοδος: Microsoft OAuth2 + Graph API

Μπορείς τώρα να χρησιμοποιήσεις:
• Email verification για νέους χρήστες  
• Password reset emails
• Admin bulk email system

🚀 Firebed OAuth2 Email Ready!
            """
            
            if sender.send_email(test_email, subject, body):
                print("✅ Test email sent successfully!")
                return True
            else:
                print("❌ Test email failed")
                return False
        else:
            print("✅ Connection test passed, email test skipped")
            return True
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    test_oauth2_email()