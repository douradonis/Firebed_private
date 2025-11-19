# Mailpit Email Integration Guide

## Επισκόπηση (Overview)

Το Mailpit είναι ένα εργαλείο δοκιμής email για developers που επιτρέπει την καταγραφή και προβολή emails τοπικά χωρίς να στέλνονται πραγματικά. Είναι ιδανικό για development και testing.

Mailpit is an email testing tool for developers that allows capturing and viewing emails locally without actually sending them. It's ideal for development and testing.

Το σύστημα υποστηρίζει τώρα τέσσερις τρόπους αποστολής email:
1. **SMTP** - Παραδοσιακή αποστολή μέσω SMTP server
2. **Resend** - Σύγχρονη αποστολή μέσω Resend API
3. **OAuth2 Outlook** - Αποστολή μέσω Microsoft Outlook με OAuth2
4. **Mailpit** - Τοπική καταγραφή emails για testing (ΝΕΟ!)

The system now supports four email sending methods:
1. **SMTP** - Traditional sending via SMTP server
2. **Resend** - Modern sending via Resend API
3. **OAuth2 Outlook** - Sending via Microsoft Outlook with OAuth2
4. **Mailpit** - Local email capture for testing (NEW!)

## Τι είναι το Mailpit; (What is Mailpit?)

Το Mailpit:
- Είναι ένας τοπικός SMTP server που τρέχει στον υπολογιστή σας
- Καταγράφει όλα τα emails που στέλνονται από την εφαρμογή
- Παρέχει ένα web UI για να δείτε τα captured emails
- ΔΕΝ στέλνει πραγματικά τα emails στους παραλήπτες
- Χρησιμοποιεί HTTP API για αποστολή emails (εκτός από SMTP)

Mailpit:
- Is a local SMTP server that runs on your computer
- Captures all emails sent from the application
- Provides a web UI to view captured emails
- Does NOT actually send emails to recipients
- Uses HTTP API for sending emails (in addition to SMTP)

**Πότε να το χρησιμοποιήσετε (When to use it):**
- Development και testing της εφαρμογής
- Δοκιμή email templates χωρίς spam σε πραγματικούς χρήστες
- CI/CD pipelines για automated testing
- Debugging email functionality

**Πότε ΝΑ ΜΗΝ το χρησιμοποιήσετε (When NOT to use it):**
- Production environment
- Όταν θέλετε πραγματική αποστολή emails σε χρήστες

## Εγκατάσταση Mailpit (Installation)

### Mac (με Homebrew)
```bash
# Εγκατάσταση
brew install mailpit

# Εκκίνηση σαν service (τρέχει πάντα στο background)
brew services start mailpit

# Ή εκκίνηση μία φορά
mailpit
```

### Docker
```bash
# Εκκίνηση Mailpit container
docker run -d \
  --name mailpit \
  -p 8025:8025 \
  -p 1025:1025 \
  axllent/mailpit

# Με authentication (προαιρετικό)
docker run -d \
  --name mailpit \
  -p 8025:8025 \
  -p 1025:1025 \
  -e MP_UI_AUTH=admin:password \
  axllent/mailpit
```

### Linux / Windows
Κατεβάστε το static binary από:
https://github.com/axllent/mailpit/releases/latest

Εξαγάγετε και τρέξτε:
```bash
./mailpit
```

## Ρύθμιση στο ScanmyData (Setup in ScanmyData)

### 1. Προσθήκη στο .env

Προσθέστε τις παρακάτω μεταβλητές στο αρχείο `.env`:

```env
# Mailpit Configuration
MAILPIT_API_URL=http://localhost:8025
SENDER_EMAIL=noreply@test.local

# Προαιρετικό: Authentication
# MAILPIT_API_USERNAME=your-username
# MAILPIT_API_PASSWORD=your-password
```

**Σημείωση:** Το `SENDER_EMAIL` μπορεί να είναι οποιοδήποτε email για testing (δεν χρειάζεται να υπάρχει).

**Note:** `SENDER_EMAIL` can be any email for testing (doesn't need to exist).

### 2. Επιλογή Provider από Admin Panel

1. Κάντε login ως admin
2. Πηγαίνετε στο **Admin Panel > Settings**
3. Επιλέξτε **Mailpit (Testing/Development)** από το dropdown "Email Provider"
4. Πατήστε **Save Settings**

### 3. Εναλλακτικά: Ρύθμιση μέσω .env

Αντί να χρησιμοποιήσετε το Admin Panel, μπορείτε να ορίσετε:

```env
EMAIL_PROVIDER=mailpit
```

## Χρήση (Usage)

### Εκκίνηση Mailpit

Βεβαιωθείτε ότι το Mailpit τρέχει πριν στείλετε emails:

```bash
# Mac (αν το εγκαταστήσατε με brew services)
brew services list | grep mailpit

# Αν δεν τρέχει
brew services start mailpit

# Ή για μία φορά
mailpit
```

### Πρόσβαση στο Web UI

Ανοίξτε τον browser στο:
```
http://localhost:8025
```

Εδώ θα δείτε όλα τα captured emails με:
- HTML preview
- Plain text version
- Email headers
- Attachments
- Source code

### Αποστολή Test Email

Από την εφαρμογή:

```python
from email_utils import send_email

# Αυτό θα σταλεί στο Mailpit αν έχετε ορίσει EMAIL_PROVIDER=mailpit
send_email(
    to_email="test@example.com",
    subject="Test Email",
    html_body="<h1>Hello from Mailpit!</h1>",
    text_body="Hello from Mailpit!"
)
```

### Εκτέλεση Tests

```bash
# Βεβαιωθείτε ότι το Mailpit τρέχει
brew services start mailpit  # Mac
# ή
docker start mailpit  # Docker

# Εκτέλεση test suite
python test_mailpit_integration.py
```

## Σύγκριση με άλλους Providers (Comparison with other providers)

| Feature | SMTP | Resend | OAuth2 Outlook | Mailpit |
|---------|------|--------|----------------|---------|
| Πραγματική αποστολή | ✅ | ✅ | ✅ | ❌ |
| Development testing | ❌ | ❌ | ❌ | ✅ |
| Web UI για προβολή | ❌ | ✅ | ❌ | ✅ |
| Χωρίς εξωτερικό service | ✅ | ❌ | ❌ | ✅ |
| Credentials απαιτούνται | ✅ | ✅ | ✅ | ❌ |
| Ιδανικό για | Production | Production | Production | Development |

## Τεχνικές Λεπτομέρειες (Technical Details)

### API Endpoint

Το Mailpit API endpoint που χρησιμοποιείται:
```
POST http://localhost:8025/api/v1/send
Content-Type: application/json
```

### Request Format

```json
{
  "from": "sender@example.com",
  "to": ["recipient@example.com"],
  "subject": "Email Subject",
  "text": "Plain text body",
  "html": "<h1>HTML body</h1>"
}
```

### Fallback στο SMTP

Αν η αποστολή μέσω Mailpit API αποτύχει, το σύστημα κάνει αυτόματα fallback στο SMTP (traditional SMTP sending).

### Authentication

Το Mailpit υποστηρίζει προαιρετικό Basic Authentication:

```env
MAILPIT_API_USERNAME=admin
MAILPIT_API_PASSWORD=secure-password
```

Για να ενεργοποιήσετε authentication στο Mailpit:

```bash
# Command line
mailpit --ui-auth-file /path/to/auth-file

# Docker
docker run -d \
  -e MP_UI_AUTH=admin:password \
  -p 8025:8025 -p 1025:1025 \
  axllent/mailpit
```

## Troubleshooting

### Πρόβλημα: "Connection refused" error

**Λύση:**
1. Βεβαιωθείτε ότι το Mailpit τρέχει:
   ```bash
   brew services list | grep mailpit
   ```
2. Ελέγξτε αν το port 8025 είναι διαθέσιμο:
   ```bash
   curl http://localhost:8025
   ```

### Πρόβλημα: Emails δεν εμφανίζονται στο Web UI

**Λύση:**
1. Ελέγξτε τα logs του Mailpit
2. Βεβαιωθείτε ότι το `EMAIL_PROVIDER=mailpit` στο .env ή στο Admin Panel
3. Κάντε restart την εφαρμογή μετά την αλλαγή

### Πρόβλημα: Authentication error

**Λύση:**
1. Βεβαιωθείτε ότι τα credentials είναι σωστά στο .env
2. Αν δεν χρησιμοποιείτε authentication, αφαιρέστε τα `MAILPIT_API_USERNAME` και `MAILPIT_API_PASSWORD`

## Χρήσιμα Links (Useful Links)

- **Mailpit GitHub**: https://github.com/axllent/mailpit
- **Mailpit Documentation**: https://mailpit.axllent.org/docs/
- **Mailpit API Documentation**: https://mailpit.axllent.org/docs/api-v1/
- **Docker Hub**: https://hub.docker.com/r/axllent/mailpit

## Παραδείγματα (Examples)

### Email Verification Testing

```python
# Δοκιμή του email verification flow
from email_utils import send_email_verification

# Στείλε verification email (θα καταγραφεί στο Mailpit)
send_email_verification(
    user_email="newuser@test.com",
    user_id=1,
    user_username="testuser"
)

# Ανοίξτε http://localhost:8025 για να δείτε το email
# Κάντε κλικ στο verification link για testing
```

### Password Reset Testing

```python
from email_utils import send_password_reset

# Στείλε password reset email
send_password_reset(
    user_email="user@test.com",
    user_id=1,
    user_username="testuser"
)

# Ελέγξτε το email στο Mailpit web UI
```

### Bulk Email Testing

```python
from email_utils import send_bulk_email_to_users

# Δοκιμή bulk emails χωρίς spam σε πραγματικούς χρήστες
user_ids = [1, 2, 3, 4, 5]
subject = "Test Announcement"
html_body = "<h1>Important Update</h1><p>This is a test.</p>"

results = send_bulk_email_to_users(user_ids, subject, html_body)
print(f"Sent: {results['sent']}, Failed: {results['failed']}")

# Όλα τα emails θα είναι στο Mailpit για έλεγχο
```

## Σύνοψη (Summary)

Το Mailpit είναι το ιδανικό εργαλείο για:
- ✅ Local development και testing
- ✅ Debugging email templates
- ✅ CI/CD testing pipelines
- ✅ Προστασία από accidental spam
- ✅ Γρήγορη προβολή και έλεγχος emails

Χρησιμοποιήστε το για development και testing, και αλλάξτε σε SMTP/Resend για production!

Use it for development and testing, and switch to SMTP/Resend for production!
