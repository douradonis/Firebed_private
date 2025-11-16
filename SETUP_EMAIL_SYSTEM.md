# Email Verification & Password Reset System - Setup Guide

This guide covers the new email verification and password reset functionality added to the system.

## What's New

✅ **Email Verification on Signup**
- New users automatically receive a verification email
- 24-hour token expiration
- Single-use token enforcement

Note: In Phase 1 this project uses Firebase Authentication for email verification and password reset flows. Firebase handles generating and sending verification/reset links. Phase 2 will introduce an SMTP-based system (custom `email_utils.py`) if you prefer to manage sending emails from this server.

✅ **Password Reset Flow**
- Users can reset forgotten passwords via email
- 1-hour token expiration
- Secure token-based authentication

✅ **Admin Bulk Email**
- Admins can send emails to selected users or all users
- Results summary with success/failure counts
- Located in admin panel: `/admin/send-email`

## Quick Start

### 1. Initialize Database

Reset the database with new email verification schema:

```bash
python3 scripts/reset_db.py
```

This creates:
- Updated `user` table with `email_verified` and `email_verified_at` fields
- New `verification_token` table for managing email and password reset tokens

### 2. Create Test Users

```bash
python3 scripts/create_test_users.py
```

This creates:
- **Admin user**: `admin` / `admin123` (admin@example.com)
- **Test user 1**: `testuser1` / `test123` (testuser1@example.com)
- **Test user 2**: `testuser2` / `test123` (testuser2@example.com)

### 3. Configure Email (Optional but Recommended)

To enable email sending, set these environment variables:

#### For Gmail:
1. Enable 2-step verification at https://myaccount.google.com/security
2. Create an App Password at https://myaccount.google.com/apppasswords
3. Copy the 16-character password
4. Set environment variables:

```bash
export SMTP_SERVER=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your-email@gmail.com
export SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx
export SENDER_EMAIL=your-email@gmail.com
export APP_URL=http://localhost:5000
```

#### For other providers:
See `.env.example` for common SMTP settings.

### 4. Run Tests

Verify the system health:

```bash
python3 test_email_system.py
```

Expected output:
```
✅ PASS: Database Schema
✅ PASS: Create User
✅ PASS: Token Management
✅ PASS: Admin Authorization
⚠️  Email Configuration INCOMPLETE (if env vars not set)
```

### 5. Start the App

```bash
python3 app.py
```

Or with Flask CLI:
```bash
export FLASK_APP=app.py
flask run
```

## Testing Workflows

### Test Email Verification (Without SMTP)

1. Go to `/auth/signup`
2. Create a new account
3. Check Flask console output - you'll see the verification token
4. Manually construct URL: `http://localhost:5000/auth/verify-email?token=<token>`
5. Visit the URL - user should be marked as verified

### Test Password Reset (Without SMTP)

1. Go to `/auth/forgot-password`
2. Enter email address
3. Check Flask console - you'll see the reset token
4. Manually construct URL: `http://localhost:5000/auth/reset-password?token=<token>`
5. Set new password - you can now login with new password

### Test Admin Bulk Email (Without SMTP)

1. Login as `admin` user
2. Go to `/admin/send-email`
3. Select users to email
4. Enter subject and message
5. Click Send - check Flask console for "Sending email to..."

### Test With Real Email (With SMTP)

Once SMTP is configured:

1. **Signup**: Create new account → check inbox for verification email
2. **Verify**: Click verify link in email → account verified
3. **Reset**: Click "Forgot password" → enter email → check inbox for reset link
4. **Admin Email**: Send bulk email to users → they receive it

## Routes

### Authentication Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/auth/verify-email` | GET | Verify email token (from email link) |
| `/auth/forgot-password` | GET, POST | Password reset request |
| `/auth/reset-password` | GET, POST | Password reset with token |

### Admin Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/admin/send-email` | GET, POST | Bulk email to users |

## Database Schema

### User Table (Fields)
- `email_verified` (Boolean) - Whether email is verified
- `email_verified_at` (DateTime) - When email was verified

### VerificationToken Table
- `id` - Primary key
- `user_id` - User reference
- `token` - Random secure token
- `token_type` - Type ('email_verify' or 'password_reset')
- `created_at` - Creation time
- `expires_at` - Token expiration time
- `used` - Whether token has been used

## API Responses

### Email Sending Errors

If email fails to send (SMTP not configured):
- Errors are logged to Flask console
- User still gets success message (email optional)
- Check Flask output for actual error

Example:
```
WARNING: Failed to send verification email to user@example.com: [Errno -2] Name or service not known
```

## Files Changed

### New Files
- `email_utils.py` - Email sending and token management
- `scripts/reset_db.py` - Database reset/initialization
- `scripts/create_test_users.py` - Test user creation
- `EMAIL_VERIFICATION_GUIDE.md` - Detailed documentation
- `SETUP_EMAIL_SYSTEM.md` - This file

### Modified Files
- `models.py` - Added email_verified fields to User; added VerificationToken model
- `auth.py` - Updated signup to send verification; added /verify-email, /forgot-password, /reset-password routes
- `app.py` - Added /admin/send-email route
- `.env.example` - Added email configuration examples

### Templates Created
- `templates/auth/forgot_password.html`
- `templates/auth/reset_password.html`
- `templates/admin/send_email.html`

## Troubleshooting

### "no such column: email_verified"
Solution: Run `python3 scripts/reset_db.py`

### Emails not sending
1. Check SMTP environment variables are set: `echo $SMTP_SERVER`
2. Check credentials are correct (especially Gmail app password)
3. Look for errors in Flask console output

### Token errors (expired/invalid)
- Email verification tokens expire after 24 hours
- Password reset tokens expire after 1 hour
- Each token can only be used once
- Check database: `SELECT * FROM verification_token WHERE token='...'`

### Database locked/corrupted
Solution: Delete and recreate:
```bash
rm -f data/app_data.db
python3 scripts/reset_db.py
python3 scripts/create_test_users.py
```

## Next Steps

1. ✅ Set up SMTP email configuration (see above)
2. ✅ Test all workflows (signup, verify, reset, admin email)
3. ✅ Deploy to production with valid SMTP credentials
4. Optional: Add email verification enforcement (require verified before full access)
5. Optional: Add email sending rate limiting

## Support

For detailed API and implementation information, see:
- `EMAIL_VERIFICATION_GUIDE.md` - Complete system documentation
- `models.py` - Database model definitions
- `email_utils.py` - Email sending implementation
- `auth.py` - Authentication routes
