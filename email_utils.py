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
EMAIL_PROVIDER = os.getenv('EMAIL_PROVIDER', 'smtp')  # 'smtp', 'oauth2_outlook', or 'resend'
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SENDER_EMAIL = os.getenv('SENDER_EMAIL', SMTP_USER)
APP_URL = os.getenv('APP_URL', 'http://localhost:5001')
OAUTH2_CREDENTIALS_FILE = os.getenv('OAUTH2_CREDENTIALS_FILE', 'outlook_oauth2_credentials.json')
RESEND_API_KEY = os.getenv('RESEND_API_KEY', '')


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
            if provider in ['smtp', 'oauth2_outlook', 'resend']:
                return provider
        except (ImportError, Exception):
            pass
    except Exception:
        pass
    
    # Fallback to environment variable
    return EMAIL_PROVIDER


def send_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send an email via SMTP, OAuth2, or Resend based on configuration"""
    
    # Get current provider from settings or environment
    provider = get_email_provider()
    
    # Route to appropriate sending function
    if provider == 'resend':
        return send_resend_email(to_email, subject, html_body, text_body)
    elif provider == 'oauth2_outlook':
        return send_oauth2_email(to_email, subject, html_body, text_body)
    else:
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
    
    try:
        import resend
        
        # Set the API key
        resend.api_key = RESEND_API_KEY
        
        # Prepare email params - Resend requires 'from' to be a verified domain
        params = {
            "from": SENDER_EMAIL or "noreply@yourdomain.com",
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        
        # Add text body if provided
        if text_body:
            params["text"] = text_body
        
        # Send email using Resend API
        email = resend.Emails.send(params)
        
        logger.info(f"Email sent via Resend to {to_email}: {subject} (ID: {email.get('id', 'unknown')})")
        return True
        
    except ImportError:
        logger.error("Resend library not available. Install it with: pip install resend")
        return False
    except Exception as e:
        logger.error(f"Failed to send Resend email to {to_email}: {e}")
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
    
    html_body = f"""
    <html>
        <body>
            <h2>Email Verification</h2>
            <p>Hello {user_username},</p>
            <p>Please verify your email address by clicking the link below:</p>
            <p><a href="{verify_url}">Verify Email</a></p>
            <p>Or paste this URL in your browser:</p>
            <p><small>{verify_url}</small></p>
            <p>This link expires in 24 hours.</p>
            <hr>
            <p>If you did not create this account, please ignore this email.</p>
        </body>
    </html>
    """
    
    return send_email(user_email, 'Email Verification - Firebed', html_body)


def send_password_reset(user_email: str, user_id: int, user_username: str) -> bool:
    """Send password reset link"""
    token = create_verification_token(user_id, 'password_reset', 1)  # 1 hour expiry
    if not token:
        return False
    
    reset_url = f"{APP_URL}/auth/reset-password?token={token}"
    
    html_body = f"""
    <html>
        <body>
            <h2>Password Reset Request</h2>
            <p>Hello {user_username},</p>
            <p>We received a request to reset your password. Click the link below to set a new password:</p>
            <p><a href="{reset_url}">Reset Password</a></p>
            <p>Or paste this URL in your browser:</p>
            <p><small>{reset_url}</small></p>
            <p>This link expires in 1 hour.</p>
            <hr>
            <p>If you did not request this, please ignore this email and your password will remain unchanged.</p>
        </body>
    </html>
    """
    
    return send_email(user_email, 'Password Reset - Firebed', html_body)


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
