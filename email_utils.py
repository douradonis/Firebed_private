"""Email utilities for sending verification emails, password resets, etc."""
import os
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

# Email config from environment
EMAIL_PROVIDER = os.getenv('EMAIL_PROVIDER', 'smtp')  # 'smtp', 'oauth2_outlook', 'resend', or 'mailgun'
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', SMTP_USER)
APP_URL = os.getenv('APP_URL', 'http://localhost:5001')
OAUTH2_CREDENTIALS_FILE = os.getenv('OAUTH2_CREDENTIALS_FILE', 'outlook_oauth2_credentials.json')
RESEND_API_KEY = os.getenv('RESEND_API_KEY', '')
RESEND_EMAIL_SENDER = os.getenv('RESEND_EMAIL_SENDER', '')
MAILGUN_API_KEY = os.getenv('MAILGUN_API_KEY', '')
MAILGUN_DOMAIN = os.getenv('MAILGUN_DOMAIN', '')
MAILGUN_SENDER_EMAIL = os.getenv('MAILGUN_SENDER_EMAIL', '')


def get_email_provider() -> str:
    """Get the current email provider from settings or environment"""
    try:
        # Try to load from settings file first (admin panel preference)
        from pathlib import Path
        import json
        
        # Try to import app's load_settings function
        try:
            from app import load_settings
            settings = load_settings()
            provider = settings.get('email_provider', '').strip()
            logger.info(f"get_email_provider: loaded from settings: {provider}")
            if provider in ['smtp', 'oauth2_outlook', 'resend', 'mailgun']:
                return provider
        except (ImportError, Exception) as e:
            logger.warning(f"get_email_provider: failed to load from settings: {e}")
            pass
    except Exception as e:
        logger.warning(f"get_email_provider: outer exception: {e}")
        pass
    
    # Fallback to environment variable
    fallback = EMAIL_PROVIDER
    logger.info(f"get_email_provider: falling back to env: {fallback}")
    return fallback


def send_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an email via SMTP, OAuth2, Resend, or Mailgun based on configuration"""
    
    # Get current provider from settings or environment
    provider = get_email_provider()
    logger.info(f"send_email called: to={to_email}, subject={subject}, provider={provider}")
    
    # Route to appropriate sending function
    if provider == 'resend':
        logger.info(f"Routing to Resend for {to_email}")
        return send_resend_email(to_email, subject, html_body, text_body)
    elif provider == 'mailgun':
        logger.info(f"Routing to Mailgun for {to_email}")
        return send_mailgun_email(to_email, subject, html_body, text_body)
    elif provider == 'oauth2_outlook':
        logger.info(f"Routing to OAuth2 for {to_email}")
        return send_oauth2_email(to_email, subject, html_body, text_body)
    else:
        logger.info(f"Routing to SMTP for {to_email}")
        return send_smtp_email(to_email, subject, html_body, text_body)


def send_smtp_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an email via traditional SMTP"""
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning(f"SMTP not configured; skipping email to {to_email}")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        
        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        
        logger.info(f"Email sent via SMTP to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send SMTP email to {to_email}: {e}")
        return False


def send_oauth2_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an email via Microsoft OAuth2"""
    try:
        from oauth2_email_handler import OutlookOAuth2EmailSender
        
        sender = OutlookOAuth2EmailSender(OAUTH2_CREDENTIALS_FILE)
        success = sender.send_email(to_email, subject, text_body or html_body, html_body)
        
        if success:
            logger.info(f"Email sent via OAuth2 to {to_email}: {subject}")
        else:
            logger.error(f"OAuth2 email send failed to {to_email}")
            
        return success
        
    except ImportError:
        logger.error("OAuth2 email handler not available")
        return False
    except Exception as e:
        logger.error(f"Failed to send OAuth2 email to {to_email}: {e}")
        return False


def send_resend_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an email via Resend API"""
    if not RESEND_API_KEY:
        logger.warning(f"Resend API key not configured; skipping email to {to_email}")
        return False
    
    # Check if using test domain - warn and suggest SMTP fallback
    sender = RESEND_EMAIL_SENDER or SENDER_EMAIL or "noreply@yourdomain.com"
    if sender == "onboarding@resend.dev":
        logger.warning(f"Using Resend test domain 'onboarding@resend.dev' - this only sends to verified emails!")
        logger.warning(f"For production, configure a verified domain in RESEND_EMAIL_SENDER")
        logger.warning(f"Falling back to SMTP for {to_email}")
        return send_smtp_email(to_email, subject, html_body, text_body)
    
    try:
        import resend
        
        # Set the API key
        resend.api_key = RESEND_API_KEY
        
        # Prepare email params - Resend requires 'from' to be a verified domain
        params = {
            "from": sender,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        
        # Add text body if provided
        if text_body:
            params["text"] = text_body
        
        # Send email using Resend API
        logger.info(f"Attempting to send via Resend: from={sender}, to={to_email}")
        email = resend.Emails.send(params)
        
        logger.info(f"Email sent via Resend to {to_email}: {subject} (ID: {email.get('id', 'unknown')})")
        return True
        
    except ImportError:
        logger.error("Resend library not available. Install it with: pip install resend")
        return False
    except Exception as e:
        logger.error(f"Failed to send Resend email to {to_email}: {e}")
        logger.error(f"Resend error details - Type: {type(e).__name__}, Args: {e.args}")
        logger.error(f"Resend sender was: {sender}, API key present: {bool(RESEND_API_KEY)}")
        
        # Fallback to SMTP if Resend fails
        logger.warning(f"Falling back to SMTP for {to_email}")
        return send_smtp_email(to_email, subject, html_body, text_body)


def send_mailgun_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an email via Mailgun HTTP API"""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        logger.warning(f"Mailgun not configured; skipping email to {to_email}")
        return False
    
    try:
        import requests
        
        # Determine sender email
        sender = MAILGUN_SENDER_EMAIL or SENDER_EMAIL or f"noreply@{MAILGUN_DOMAIN}"
        
        # Mailgun API endpoint for sending emails
        url = f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages"
        
        # Prepare email data - Mailgun uses form-encoded data
        data = {
            "from": sender,
            "to": to_email,
            "subject": subject,
            "html": html_body,
        }
        
        # Add text body if provided
        if text_body:
            data["text"] = text_body
        
        # Send email using Mailgun HTTP API with basic auth
        logger.info(f"Attempting to send via Mailgun: from={sender}, to={to_email}, domain={MAILGUN_DOMAIN}")
        response = requests.post(
            url,
            auth=("api", MAILGUN_API_KEY),
            data=data,
            timeout=10
        )
        
        # Check response
        if response.status_code == 200:
            response_data = response.json()
            message_id = response_data.get('id', 'unknown')
            logger.info(f"Email sent via Mailgun to {to_email}: {subject} (ID: {message_id})")
            return True
        else:
            logger.error(f"Mailgun API error: Status {response.status_code}, Response: {response.text}")
            return False
        
    except ImportError:
        logger.error("Requests library not available. Install it with: pip install requests")
        return False
    except Exception as e:
        logger.error(f"Failed to send Mailgun email to {to_email}: {e}")
        logger.error(f"Mailgun error details - Type: {type(e).__name__}, Args: {e.args}")
        logger.error(f"Mailgun sender was: {sender}, Domain: {MAILGUN_DOMAIN}, API key present: {bool(MAILGUN_API_KEY)}")
        return False


def create_verification_token(user_id: int, token_type: str = 'email_verify', expires_in_hours: int = 24) -> Optional[str]:
    """Create a verification/reset token and store it in DB"""
    try:
        from models import db, VerificationToken
        from datetime import datetime, timedelta, timezone
        
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)
        
        vtoken = VerificationToken(
            user_id=user_id,
            token=token,
            token_type=token_type,
            expires_at=expires_at
        )
        db.session.add(vtoken)
        db.session.commit()
        return token
    except Exception as e:
        logger.error(f"Failed to create verification token: {e}")
        return None


def verify_token(token: str, token_type: str) -> Optional[int]:
    """Verify a token and return user_id if valid; mark token as used"""
    try:
        from models import db, VerificationToken
        
        vtoken = VerificationToken.query.filter_by(token=token, token_type=token_type).first()
        if not vtoken or not vtoken.is_valid():
            return None
        
        vtoken.used = True
        db.session.commit()
        return vtoken.user_id
    except Exception as e:
        logger.error(f"Failed to verify token: {e}")
        return None


def send_email_verification(user_email: str, user_id: int, user_username: str) -> bool:
    """Send email verification link"""
    token = create_verification_token(user_id, 'email_verify', 24)
    if not token:
        return False
    
    verify_url = f"{APP_URL}/auth/verify-email?token={token}"
    logo_url = f"{APP_URL}/icons/scanmydata_logo_3000w.png"
    
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f8f9fa;">
                <div style="background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <img src="{logo_url}" alt="ScanmyData" style="height: 80px; width: auto;">
                    </div>
                    <h2 style="color: #0ea5e9; text-align: center;">Επαλήθευση Email - ScanmyData</h2>
                    <p>Γεια σου {user_username},</p>
                    <p>Σε ευχαριστούμε που εγγράφηκες στο <strong>ScanmyData</strong>! Για να ενεργοποιήσεις τον λογαριασμό σου και να έχεις πρόσβαση σε όλες τις δυνατότητες, παρακαλώ επαλήθευσε τη διεύθυνση email σου:</p>
                    <p style="margin: 25px 0; text-align: center;">
                        <a href="{verify_url}" style="background-color: #0ea5e9; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold;">✅ Επαλήθευση Email</a>
                    </p>
                    <div style="background: #e8f4fd; border-left: 4px solid #0ea5e9; padding: 15px; margin: 20px 0; border-radius: 4px;">
                        <strong>📧 Τι θα συμβεί μετά:</strong><br>
                        • Θα ενεργοποιηθεί ο λογαριασμός σου<br>
                        • Θα μπορείς να κάνεις login<br>
                        • Θα έχεις πρόσβαση στο dashboard<br>
                        • Θα λαμβάνεις σημαντικές ενημερώσεις
                    </div>
                    <p style="font-size: 14px; color: #666;"><strong>Δεν μπορείς να κάνεις κλικ στο κουμπί;</strong><br>Αντίγραψε αυτό το URL στον browser σου:</p>
                    <p style="background-color: #f3f4f6; padding: 10px; border-radius: 5px; word-break: break-all; font-size: 12px;"><small>{verify_url}</small></p>
                    <p style="font-size: 12px; color: #999; text-align: center;">Ο σύνδεσμος λήγει σε 24 ώρες.</p>
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
                    <p style="color: #6b7280; font-size: 0.9em; text-align: center;">🔒 Εάν δεν δημιούργησες αυτόν τον λογαριασμό, παρακαλώ αγνόησε αυτό το email.</p>
                    <div style="text-align: center; margin-top: 30px;">
                        <img src="{logo_url}" alt="ScanmyData" style="height: 50px; width: auto; opacity: 0.6;">
                        <p style="font-size: 12px; color: #999; margin-top: 10px;"><strong>ScanmyData Team</strong></p>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """
    
    text_body = f"""
ScanmyData - Επαλήθευση Email

Γεια σου {user_username}!

Σε ευχαριστούμε που εγγράφηκες στο ScanmyData!
Για να ενεργοποιήσεις τον λογαριασμό σου, κάνε κλικ στο παρακάτω link:

{verify_url}

Τι θα συμβεί μετά:
✅ Θα ενεργοποιηθεί ο λογαριασμός σου
✅ Θα μπορείς να κάνεις login  
✅ Θα έχεις πρόσβαση στο dashboard

🔒 Ασφάλεια: Αν δεν δημιούργησες εσύ αυτόν τον λογαριασμό, αγνόησε αυτό το email.

ScanmyData Team
Ο σύνδεσμος λήγει σε 24 ώρες.
    """
    
    return send_email(user_email, 'Επαλήθευση Email - ScanmyData', html_body, text_body)


def send_password_reset(user_email: str, user_id: int, user_username: str) -> bool:
    """Send password reset link"""
    token = create_verification_token(user_id, 'password_reset', 1)  # 1 hour expiry
    if not token:
        return False
    
    reset_url = f"{APP_URL}/auth/reset-password?token={token}"
    logo_url = f"{APP_URL}/icons/scanmydata_logo_3000w.png"
    
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f8f9fa;">
                <div style="background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                    <div style="text-align: center; margin-bottom: 30px;">
                        <img src="{logo_url}" alt="ScanmyData" style="height: 80px; width: auto;">
                    </div>
                    <h2 style="color: #f39c12; text-align: center;">🔐 Επαναφορά Κωδικού - ScanmyData</h2>
                    <p>Γεια σου {user_username},</p>
                    <p>Λάβαμε αίτημα για επαναφορά του κωδικού σου στο <strong>ScanmyData</strong>. Πάτησε τον παρακάτω σύνδεσμο για να ορίσεις νέο κωδικό:</p>
                    <p style="margin: 25px 0; text-align: center;">
                        <a href="{reset_url}" style="background-color: #f39c12; color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; display: inline-block; font-weight: bold;">🔐 Επαναφορά Κωδικού</a>
                    </p>
                    <div style="background: #e8f4fd; border-left: 4px solid #3498db; padding: 15px; margin: 20px 0; border-radius: 4px;">
                        <strong>📋 Διαδικασία Επαναφοράς:</strong><br>
                        1. Κάνε κλικ στο κουμπί παραπάνω<br>
                        2. Εισάγαγε νέο κωδικό (τουλάχιστον 6 χαρακτήρες)<br>
                        3. Επιβεβαίωσε τον νέο κωδικό<br>
                        4. Κάνε login με τα νέα στοιχεία
                    </div>
                    <div style="background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 6px; margin: 20px 0;">
                        <strong>⚠️ Σημαντικό:</strong><br>
                        • Το link ισχύει για 1 ώρα από την αποστολή<br>
                        • Αν δεν ζήτησες εσύ επαναφορά, αγνόησε αυτό το email<br>
                        • Ο κωδικός σου δεν θα αλλάξει χωρίς την επιβεβαίωσή σου
                    </div>
                    <p style="font-size: 14px; color: #666;"><strong>Δεν μπορείς να κάνεις κλικ στο κουμπί;</strong><br>Αντίγραψε αυτό το URL στον browser σου:</p>
                    <p style="background-color: #f3f4f6; padding: 10px; border-radius: 5px; word-break: break-all; font-size: 12px;"><small>{reset_url}</small></p>
                    <p style="font-size: 12px; color: #999; text-align: center;">Ο σύνδεσμος λήγει σε 1 ώρα.</p>
                    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;">
                    <p style="color: #6b7280; font-size: 0.9em; text-align: center;">Εάν δεν ζήτησες αυτό, παρακαλώ αγνόησε αυτό το email και ο κωδικός σου θα παραμείνει αμετάβλητος.</p>
                    <div style="text-align: center; margin-top: 30px;">
                        <img src="{logo_url}" alt="ScanmyData" style="height: 50px; width: auto; opacity: 0.6;">
                        <p style="font-size: 12px; color: #999; margin-top: 10px;"><strong>ScanmyData Security Team</strong></p>
                    </div>
                </div>
            </div>
        </body>
    </html>
    """
    
    text_body = f"""
ScanmyData - Επαναφορά Κωδικού

Γεια σου {user_username}!

Λάβαμε αίτημα για επαναφορά του κωδικού σου στο ScanmyData.

Για να ορίσεις νέο κωδικό, κάνε κλικ στο link:
{reset_url}

Διαδικασία:
1. Κάνε κλικ στο link
2. Εισάγαγε νέο κωδικό  
3. Επιβεβαίωσε τον κωδικό
4. Login με τα νέα στοιχεία

⚠️ Σημαντικό:
• Το link ισχύει για 1 ώρα
• Αν δεν ζήτησες επαναφορά, αγνόησε το email

ScanmyData Security Team
    """
    
    return send_email(user_email, 'Επαναφορά Κωδικού - ScanmyData', html_body, text_body)


def send_bulk_email_to_users(user_ids: list, subject: str, html_body: str) -> dict:
    """Send email to multiple users (admin function)"""
    from models import User
    
    results = {'sent': 0, 'failed': 0, 'errors': []}
    
    for uid in user_ids:
        try:
            user = User.query.get(uid)
            if not user or not user.email:
                results['failed'] += 1
                results['errors'].append(f'User {uid}: no email')
                continue
            
            if send_email(user.email, subject, html_body):
                results['sent'] += 1
            else:
                results['failed'] += 1
                results['errors'].append(f'User {uid}: send failed')
        except Exception as e:
            results['failed'] += 1
            results['errors'].append(f'User {uid}: {str(e)}')
    
    return results
