# Resend Email Integration Guide

## Επισκόπηση (Overview)

Το σύστημα υποστηρίζει τώρα τρεις τρόπους αποστολής email:
1. **SMTP** - Παραδοσιακή αποστολή μέσω SMTP server
2. **Resend** - Σύγχρονη αποστολή μέσω Resend API
3. **OAuth2 Outlook** - Αποστολή μέσω Microsoft Outlook με OAuth2

The system now supports three email sending methods:
1. **SMTP** - Traditional sending via SMTP server
2. **Resend** - Modern sending via Resend API
3. **OAuth2 Outlook** - Sending via Microsoft Outlook with OAuth2

## Απάντηση στην Ερώτηση για Templates

**ΔΕΝ χρειάζεται** να δημιουργήσετε templates μέσα στην εφαρμογή του Resend. Το σύστημα στέλνει το ίδιο HTML περιεχόμενο που χρησιμοποιείται ήδη με το SMTP. Τα emails που στέλνονται μέσω Resend είναι **ακριβώς τα ίδια** με αυτά που στέλνονται μέσω SMTP.

**You do NOT need** to create templates in the Resend application. The system sends the same HTML content already used with SMTP. Emails sent via Resend are **exactly the same** as those sent via SMTP.

## Ρύθμιση (Setup)

### 1. Εγκατάσταση Dependencies

Το Resend SDK προστέθηκε ήδη στο `requirements.txt`:

```bash
pip install -r requirements.txt
```

### 2. Ρύθμιση Resend API Key

Προσθέστε το Resend API key στο αρχείο `.env`:

```env
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
SENDER_EMAIL=noreply@yourdomain.com
```

**Σημαντικό:** Το email που χρησιμοποιείτε στο `SENDER_EMAIL` πρέπει να είναι από domain που έχετε επαληθεύσει στο Resend dashboard.

**Important:** The email you use in `SENDER_EMAIL` must be from a domain you have verified in the Resend dashboard.

### 3. Επαλήθευση Domain στο Resend

1. Πηγαίνετε στο [Resend Dashboard](https://resend.com/domains)
2. Προσθέστε το domain σας
3. Προσθέστε τα DNS records που σας δίνει το Resend
4. Περιμένετε την επαλήθευση (συνήθως λίγα λεπτά)

### 4. Ενεργοποίηση Resend από το Admin Panel

1. Συνδεθείτε ως admin
2. Πηγαίνετε στο `/admin/settings`
3. Επιλέξτε "Resend (API-based)" από το dropdown "Email Provider"
4. Κάντε κλικ "Save Settings"

## Χρήση (Usage)

### Αλλαγή Email Provider

Ο admin μπορεί να αλλάξει τον email provider οποιαδήποτε στιγμή από το admin panel:

1. **Admin Panel** → **Settings**
2. Επιλέξτε τον επιθυμητό provider από το dropdown
3. Save

### Τα Email που Στέλνονται

Όλα τα παρακάτω emails χρησιμοποιούν το ίδιο σύστημα και τα ίδια templates:

1. **Email Verification** - Όταν κάποιος κάνει εγγραφή
2. **Password Reset** - Όταν κάποιος ξεχάσει τον κωδικό του
3. **Bulk Emails** - Όταν ο admin στέλνει email σε πολλούς χρήστες

Ανεξάρτητα από το ποιον provider επιλέξετε (SMTP ή Resend), τα emails θα είναι **ακριβώς τα ίδια**.

## Τεχνικές Λεπτομέρειες (Technical Details)

### Αρχιτεκτονική

- Η συνάρτηση `send_email()` ελέγχει τις ρυθμίσεις και καλεί τον κατάλληλο provider
- Η συνάρτηση `get_email_provider()` διαβάζει την επιλογή από το settings file
- Το settings file είναι `data/credentials_settings.json`

### Code Flow

```python
send_email()
  → get_email_provider()  # Reads from settings or env
  → Calls appropriate function:
    - send_smtp_email() for SMTP
    - send_resend_email() for Resend
    - send_oauth2_email() for OAuth2
```

### Email Templates

Τα templates είναι hardcoded στο `email_utils.py`:

- `send_email_verification()` - Δημιουργεί HTML για verification email
- `send_password_reset()` - Δημιουργεί HTML για password reset email
- `send_bulk_email_to_users()` - Στέλνει custom HTML που δίνει ο admin

Και τα τρία χρησιμοποιούν την ίδια HTML δομή ανεξάρτητα από τον provider.

## Δοκιμή (Testing)

Τρέξτε τα tests για να επαληθεύσετε τη λειτουργικότητα:

```bash
python3 test_resend_integration.py
```

Αναμενόμενο αποτέλεσμα:
```
✅ PASS: Resend Configuration
✅ PASS: Email Provider Settings  
✅ PASS: Resend Email Function
✅ PASS: Email Templates

Total: 4/4 tests passed
🎉 All tests passed!
```

## Troubleshooting

### "Resend API key not configured"

**Λύση:** Προσθέστε το `RESEND_API_KEY` στο `.env` file.

### "Domain not verified"

**Λύση:** Επαληθεύστε το domain σας στο Resend dashboard πριν στείλετε emails.

### "Failed to send Resend email"

**Ελέγξτε:**
1. Το API key είναι σωστό
2. Το SENDER_EMAIL είναι από verified domain
3. Τα logs για το ακριβές error message

## Σύγκριση Providers (Provider Comparison)

| Feature | SMTP | Resend | OAuth2 Outlook |
|---------|------|--------|----------------|
| Setup Complexity | Μέτρια | Εύκολη | Δύσκολη |
| Reliability | Καλή | Πολύ Καλή | Καλή |
| Speed | Μέτρια | Γρήγορη | Μέτρια |
| Deliverability | Εξαρτάται | Πολύ Καλή | Πολύ Καλή |
| Cost | Δωρεάν* | Free tier + paid | Δωρεάν* |
| Templates | ✅ Same | ✅ Same | ✅ Same |

*Εξαρτάται από τον email provider που χρησιμοποιείτε

## Support

Για βοήθεια ή ερωτήσεις, ελέγξτε:
- Τα logs του application (`firebed.log`)
- Το Resend dashboard για λεπτομέρειες αποστολής
- Τα test scripts για παραδείγματα χρήσης
