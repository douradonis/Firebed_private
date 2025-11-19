# Mailpit Quick Start Guide / Οδηγός Γρήγορης Εκκίνησης Mailpit

## Απλή Εγκατάσταση και Χρήση (Simple Installation and Usage)

### 1. Εγκατάσταση Mailpit (Install Mailpit)

**Mac:**
```bash
brew install mailpit
brew services start mailpit
```

**Docker:**
```bash
docker run -d --name mailpit -p 8025:8025 -p 1025:1025 axllent/mailpit
```

**Linux/Windows:**
Download from: https://github.com/axllent/mailpit/releases/latest

### 2. Ρύθμιση .env (Configure .env)

Προσθέστε αυτές τις γραμμές στο `.env` file:
(Add these lines to your `.env` file:)

```env
MAILPIT_API_URL=http://localhost:8025
SENDER_EMAIL=noreply@test.local
```

### 3. Επιλογή από Admin Panel (Select from Admin Panel)

1. Login ως admin / Login as admin
2. Admin Panel > Settings
3. Email Provider → επιλέξτε / select **"Mailpit (Testing/Development)"**
4. Save Settings

### 4. Έλεγχος (Test)

```bash
python test_mailpit_integration.py
```

### 5. Προβολή Emails (View Emails)

Ανοίξτε τον browser / Open browser:
```
http://localhost:8025
```

## Τι Κάνει το Mailpit; (What Does Mailpit Do?)

✅ Καταγράφει όλα τα emails τοπικά (Captures all emails locally)
✅ ΔΕΝ στέλνει πραγματικά emails (Does NOT send real emails)
✅ Εμφανίζει emails σε web UI (Shows emails in web UI)
✅ Ιδανικό για testing (Perfect for testing)

## Πότε να το Χρησιμοποιήσετε; (When to Use It?)

✅ Development και testing
✅ Δοκιμή email templates
✅ CI/CD testing
✅ Αποφυγή spam σε πραγματικούς χρήστες (Avoid spamming real users)

❌ ΜΗΝ το χρησιμοποιήσετε σε production (DO NOT use in production)

## Σύντομη Σύγκριση (Quick Comparison)

| Provider | Πραγματική Αποστολή | Ιδανικό για |
|----------|---------------------|-------------|
| SMTP | ✅ Ναι / Yes | Production |
| Resend | ✅ Ναι / Yes | Production |
| Mailpit | ❌ Όχι / No | Development/Testing |

## Γρήγορη Αντιμετώπιση Προβλημάτων (Quick Troubleshooting)

**Πρόβλημα:** "Connection refused"
**Λύση:** Ξεκινήστε το Mailpit
```bash
brew services start mailpit  # Mac
docker start mailpit         # Docker
```

**Πρόβλημα:** Emails δεν εμφανίζονται
**Λύση:** 
1. Ελέγξτε ότι EMAIL_PROVIDER=mailpit
2. Restart την εφαρμογή
3. Ελέγξτε http://localhost:8025

## Περισσότερες Πληροφορίες (More Information)

Δείτε το αρχείο: `MAILPIT_INTEGRATION.md`
See file: `MAILPIT_INTEGRATION.md`

## Υποστήριξη (Support)

- Mailpit GitHub: https://github.com/axllent/mailpit
- Mailpit Docs: https://mailpit.axllent.org/docs/

## Παράδειγμα Χρήσης (Usage Example)

```python
# Το σύστημα στέλνει αυτόματα μέσω Mailpit αν το έχετε επιλέξει
# System automatically sends via Mailpit if selected

from email_utils import send_email

send_email(
    to_email="test@example.com",
    subject="Test Email",
    html_body="<h1>Hello!</h1><p>This is a test.</p>"
)

# Δείτε το email στο http://localhost:8025
# View the email at http://localhost:8025
```

---

**Σημείωση:** Το Mailpit χρησιμοποιεί τα SMTP credentials από το .env για το sender email, όπως ζητήθηκε.

**Note:** Mailpit uses SMTP credentials from .env for sender email, as requested.
