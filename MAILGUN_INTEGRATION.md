# Mailgun HTTP API Integration Guide

## Επισκόπηση (Overview)

Το σύστημα υποστηρίζει τώρα **τέσσερις** τρόπους αποστολής email:
1. **SMTP** - Παραδοσιακή αποστολή μέσω SMTP server (ports 25/465/587)
2. **Resend** - Σύγχρονη αποστολή μέσω Resend API (HTTP)
3. **Mailgun** - Αποστολή μέσω Mailgun HTTP API (HTTP) - **ΝΕΟ!**
4. **OAuth2 Outlook** - Αποστολή μέσω Microsoft Outlook με OAuth2

The system now supports **four** email sending methods:
1. **SMTP** - Traditional sending via SMTP server (ports 25/465/587)
2. **Resend** - Modern sending via Resend API (HTTP)
3. **Mailgun** - Sending via Mailgun HTTP API (HTTP) - **NEW!**
4. **OAuth2 Outlook** - Sending via Microsoft Outlook with OAuth2

---

## Γιατί Mailgun; (Why Mailgun?)

### Πρόβλημα στο Render Free Tier
Το **Render free tier** μπλοκάρει τα SMTP ports (25, 465, 587), οπότε δεν μπορείτε να στείλετε email με παραδοσιακό SMTP.

### Λύση: Mailgun HTTP API
Το **Mailgun HTTP API** χρησιμοποιεί HTTP (port 443) αντί για SMTP ports, οπότε:
- ✅ **Δουλεύει στο Render free tier** (και άλλες πλατφόρμες που μπλοκάρουν SMTP)
- ✅ **Δεν χρειάζεται SMTP relay**
- ✅ **Χρησιμοποιεί απλά HTTP requests**
- ✅ **Τα ίδια templates με SMTP/Resend**

### Problem on Render Free Tier
**Render free tier** blocks SMTP ports (25, 465, 587), so you cannot send emails with traditional SMTP.

### Solution: Mailgun HTTP API
**Mailgun HTTP API** uses HTTP (port 443) instead of SMTP ports, so:
- ✅ **Works on Render free tier** (and other platforms that block SMTP)
- ✅ **No SMTP relay needed**
- ✅ **Uses simple HTTP requests**
- ✅ **Same templates as SMTP/Resend**

---

## Σύγκριση: SMTP vs HTTP API (Comparison)

| Χαρακτηριστικό | SMTP | Mailgun HTTP API |
|----------------|------|------------------|
| **Ports που χρησιμοποιεί** | 25, 465, 587 | 443 (HTTPS) |
| **Render Free Tier** | ❌ ΔΕΝ δουλεύει | ✅ Δουλεύει |
| **Templates** | ✅ Ίδια | ✅ Ίδια |
| **Ρύθμιση** | Μέτρια | Εύκολη |
| **Αξιοπιστία** | Καλή | Πολύ Καλή |
| **Deliverability** | Εξαρτάται | Πολύ Καλή |
| **Κόστος** | Δωρεάν* | Free tier + paid |

*Εξαρτάται από τον SMTP provider

---

## Ρύθμιση (Setup)

### 1. Δημιουργία Mailgun Account

1. Πηγαίνετε στο [Mailgun](https://www.mailgun.com/)
2. Κάντε εγγραφή (δωρεάν trial με 5,000 emails/month για 3 μήνες)
3. Επαληθεύστε το email σας

### 2. Ρύθμιση Domain στο Mailgun

#### Επιλογή A: Χρήση Sandbox Domain (για δοκιμές)
Το Mailgun σας δίνει ένα sandbox domain αυτόματα (π.χ. `sandboxXXXXXXXX.mailgun.org`):
- ✅ Έτοιμο για άμεση χρήση
- ⚠️ Στέλνει μόνο σε **authorized recipients** (emails που προσθέτετε εσείς)
- Καλό για development/testing

**Προσθήκη authorized recipient:**
1. Πηγαίνετε στο Dashboard → Sending → Overview
2. Στο "Authorized Recipients" κάντε κλικ "Add Recipient"
3. Προσθέστε το email σας
4. Επιβεβαιώστε το από το inbox σας

#### Επιλογή B: Χρήση Custom Domain (για production)
Για να στέλνετε σε όλους (production):
1. Πηγαίνετε στο Dashboard → Sending → Domains
2. Κάντε κλικ "Add New Domain"
3. Εισάγετε το domain σας (π.χ. `mg.yourdomain.com`)
4. Προσθέστε τα DNS records που σας δείχνει (MX, TXT, CNAME)
5. Περιμένετε επαλήθευση (συνήθως λίγα λεπτά)

**DNS Records που χρειάζονται:**
- **TXT** για SPF
- **TXT** για DKIM
- **MX** για receiving
- **CNAME** για tracking

### 3. Λήψη API Key

1. Πηγαίνετε στο Dashboard → Settings → API Keys
2. Αντιγράψτε το **Private API key** (ή δημιουργήστε νέο)
   - Μοιάζει με: `key-xxxxxxxxxxxxxxxxxxxxxxxx`

### 4. Ρύθμιση Environment Variables

Προσθέστε τις μεταβλητές στο `.env` file σας:

```env
# Mailgun Configuration
MAILGUN_API_KEY=key-xxxxxxxxxxxxxxxxxxxxxxxx
MAILGUN_DOMAIN=sandboxXXXXXXXX.mailgun.org
# ή για custom domain:
# MAILGUN_DOMAIN=mg.yourdomain.com

# Sender email (optional - defaults to noreply@{MAILGUN_DOMAIN})
MAILGUN_SENDER_EMAIL=noreply@sandboxXXXXXXXX.mailgun.org
```

**Σημαντικό:**
- Το `MAILGUN_DOMAIN` πρέπει να είναι ακριβώς όπως εμφανίζεται στο Mailgun dashboard
- Το `MAILGUN_SENDER_EMAIL` πρέπει να χρησιμοποιεί το `MAILGUN_DOMAIN`

### 5. Ενεργοποίηση Mailgun από το Admin Panel

1. Συνδεθείτε ως admin
2. Πηγαίνετε στο `/admin/settings`
3. Επιλέξτε **"Mailgun (HTTP API)"** από το dropdown "Email Provider"
4. Κάντε κλικ **"Save Settings"**

---

## Render Deployment

### Ρύθμιση Environment Variables στο Render

1. Πηγαίνετε στο Render Dashboard
2. Επιλέξτε το service σας
3. Πηγαίνετε στο **Environment** tab
4. Προσθέστε τις μεταβλητές:
   ```
   MAILGUN_API_KEY = key-xxxxxxxxxxxxxxxxxxxxxxxx
   MAILGUN_DOMAIN = sandboxXXXXXXXX.mailgun.org
   MAILGUN_SENDER_EMAIL = noreply@sandboxXXXXXXXX.mailgun.org
   EMAIL_PROVIDER = mailgun
   ```
5. Κάντε **Deploy** (ή περιμένετε auto-deploy)

### Επαλήθευση στο Render

Μετά το deployment:
1. Ανοίξτε την εφαρμογή σας
2. Πηγαίνετε στο `/admin/settings`
3. Επιβεβαιώστε ότι το "Mailgun (HTTP API)" είναι επιλεγμένο
4. Δοκιμάστε με signup (θα στείλει verification email)

---

## Χρήση (Usage)

### Email που Στέλνονται Αυτόματα

Το σύστημα στέλνει αυτόματα τα παρακάτω emails μέσω Mailgun:

1. **Email Verification** - Όταν κάποιος κάνει εγγραφή
   - Περιέχει verification link
   - Λήγει σε 24 ώρες

2. **Password Reset** - Όταν κάποιος πατήσει "Forgot Password"
   - Περιέχει reset link
   - Λήγει σε 1 ώρα

3. **Bulk Emails** - Όταν ο admin στέλνει email σε πολλούς χρήστες
   - Custom HTML από admin panel

### Τα Templates είναι Ίδια

Ανεξάρτητα από τον provider (SMTP/Resend/Mailgun/OAuth2), τα emails είναι **ακριβώς τα ίδια**:
- Ίδιο HTML design
- Ίδια λογότυπα και εικόνες
- Ίδιο περιεχόμενο
- Ίδια λειτουργικότητα

**ΔΕΝ χρειάζεται** να δημιουργήσετε templates στο Mailgun dashboard.

---

## Δοκιμή (Testing)

### Automated Tests

Τρέξτε το test script:

```bash
python3 test_mailgun_integration.py
```

Αναμενόμενο αποτέλεσμα:
```
✅ PASS: Mailgun Configuration
✅ PASS: Email Provider Settings  
✅ PASS: Mailgun Email Function
✅ PASS: Email Templates Compatibility
✅ PASS: HTTP API Compatibility

Total: 5/5 tests passed
🎉 All tests passed!
```

### Manual Testing

#### Test 1: Email Verification
1. Δημιουργήστε νέο λογαριασμό
2. Ελέγξτε το inbox σας (ή authorized recipient)
3. Κάντε κλικ στο verification link

#### Test 2: Password Reset
1. Πηγαίνετε στο login page
2. Κάντε κλικ "Forgot Password"
3. Εισάγετε το email σας
4. Ελέγξτε το inbox σας
5. Κάντε κλικ στο reset link

#### Test 3: Bulk Email (Admin)
1. Login ως admin
2. Πηγαίνετε στο admin panel
3. Βρείτε τη λειτουργία bulk email
4. Στείλτε test email σε επιλεγμένους χρήστες

### Έλεγχος στο Mailgun Dashboard

1. Πηγαίνετε στο [Mailgun Dashboard](https://app.mailgun.com/)
2. Επιλέξτε **Sending → Logs**
3. Δείτε:
   - Sent messages
   - Delivery status
   - Any errors
   - Recipient details

---

## Τεχνικές Λεπτομέρειες (Technical Details)

### Αρχιτεκτονική

```python
send_email(to, subject, html, text)
  ↓
get_email_provider() → 'mailgun'
  ↓
send_mailgun_email(to, subject, html, text)
  ↓
HTTP POST to https://api.mailgun.net/v3/{domain}/messages
  ↓
Mailgun API → Email Delivered
```

### HTTP API Endpoint

```python
url = f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages"

# Authentication: Basic Auth
auth = ("api", MAILGUN_API_KEY)

# Data: Form-encoded
data = {
    "from": "noreply@yourdomain.com",
    "to": "user@example.com",
    "subject": "Email Subject",
    "html": "<h1>HTML Content</h1>",
    "text": "Text Content"  # optional
}

# Request
response = requests.post(url, auth=auth, data=data)
```

### Πλεονεκτήματα HTTP API

1. **Χωρίς SMTP Ports** - Χρησιμοποιεί μόνο HTTPS (port 443)
2. **Εύκολη Διάγνωση** - HTTP status codes και JSON responses
3. **Καλύτερο Error Handling** - Λεπτομερή error messages
4. **Καλύτερη Παρακολούθηση** - Dashboard με πλήρη logs
5. **Attachment Support** - Μπορεί να στείλει attachments (αν χρειαστεί)

---

## Troubleshooting

### "Mailgun not configured"

**Αιτία:** Λείπουν environment variables

**Λύση:**
```env
MAILGUN_API_KEY=key-xxxxxxxxxxxxxxxxxxxxxxxx
MAILGUN_DOMAIN=sandboxXXXXXXXX.mailgun.org
```

### "Mailgun API error: Status 401"

**Αιτία:** Λάθος API key

**Λύση:**
1. Ελέγξτε το API key στο Mailgun dashboard
2. Βεβαιωθείτε ότι χρησιμοποιείτε το **Private API key**
3. Ελέγξτε για extra spaces στο `.env`

### "Mailgun API error: Status 400"

**Αιτία:** Λάθος domain ή invalid sender

**Λύση:**
1. Ελέγξτε ότι το `MAILGUN_DOMAIN` είναι σωστό
2. Βεβαιωθείτε ότι το sender email χρησιμοποιεί το domain
3. Για sandbox: Προσθέστε τον recipient στα authorized recipients

### "Free account sending limit reached"

**Αιτία:** Φτάσατε το όριο του free plan

**Λύση:**
1. Αναβαθμίστε σε paid plan
2. Ή περιμένετε να περάσει το billing cycle
3. Ή χρησιμοποιήστε άλλον provider προσωρινά

### Emails δεν φτάνουν

**Έλεγχοι:**
1. **Spam folder** - Ελέγξτε τον spam
2. **Authorized recipients** - Για sandbox, πρέπει να είναι authorized
3. **Domain verification** - Για custom domain, πρέπει να είναι verified
4. **Logs** - Ελέγξτε το Mailgun dashboard logs
5. **Application logs** - Ελέγξτε το `firebed.log`

---

## Σύγκριση Providers (Provider Comparison)

| Feature | SMTP | Resend | Mailgun | OAuth2 |
|---------|------|--------|---------|--------|
| **Render Free Tier** | ❌ No | ✅ Yes | ✅ Yes | ❌ No |
| **Setup** | Μέτρια | Εύκολη | Εύκολη | Δύσκολη |
| **Reliability** | Καλή | Πολύ Καλή | Πολύ Καλή | Καλή |
| **Deliverability** | Μέτρια | Εξαιρετική | Εξαιρετική | Πολύ Καλή |
| **Free Tier** | Varies | 100/day | 5K/month* | N/A |
| **Logs/Dashboard** | ❌ No | ✅ Yes | ✅ Yes | Limited |
| **Templates** | ✅ Same | ✅ Same | ✅ Same | ✅ Same |

*Mailgun: 5,000 emails/month for 3 months trial, then paid

### Πότε να χρησιμοποιήσετε κάθε provider:

- **SMTP**: Όταν έχετε δικό σας email server ή χρησιμοποιείτε provider που δεν μπλοκάρει SMTP
- **Resend**: Για production apps με clean API και καλό deliverability
- **Mailgun**: Για Render free tier ή όταν θέλετε enterprise features
- **OAuth2**: Όταν χρησιμοποιείτε Microsoft 365/Outlook

---

## Mailgun Features (Advanced)

### Email Validation API

Το Mailgun έχει και API για validation (extra):
```python
import requests

def validate_email(email):
    url = f"https://api.mailgun.net/v4/address/validate"
    response = requests.get(
        url,
        auth=("api", MAILGUN_API_KEY),
        params={"address": email}
    )
    return response.json()
```

### Tracking Features

Στο Mailgun dashboard μπορείτε να δείτε:
- Opens (πόσοι άνοιξαν το email)
- Clicks (πόσοι έκαναν κλικ σε links)
- Bounces (failed deliveries)
- Complaints (spam reports)

### Webhooks

Μπορείτε να ρυθμίσετε webhooks για:
- Delivery confirmation
- Bounce notifications
- Spam complaints
- Click tracking

---

## Support & Resources

### Επίσημα Resources

- [Mailgun Documentation](https://documentation.mailgun.com/)
- [API Reference](https://documentation.mailgun.com/en/latest/api-intro.html)
- [Dashboard](https://app.mailgun.com/)

### Σε αυτό το Project

- Test script: `test_mailgun_integration.py`
- Email utils: `email_utils.py`
- Admin settings: `/admin/settings`
- Logs: `firebed.log`

### Troubleshooting Steps

1. Ελέγξτε logs: `tail -f firebed.log`
2. Δοκιμάστε test script: `python3 test_mailgun_integration.py`
3. Ελέγξτε Mailgun dashboard logs
4. Επιβεβαιώστε environment variables
5. Δοκιμάστε με sandbox domain πρώτα

---

## Επόμενα Βήματα (Next Steps)

1. ✅ **Ρύθμιση** - Δημιουργήστε Mailgun account και πάρτε API key
2. ✅ **Configuration** - Προσθέστε environment variables
3. ✅ **Testing** - Τρέξτε tests και δοκιμάστε signup flow
4. ✅ **Production** - Deploy στο Render με Mailgun enabled
5. ⚠️ **Custom Domain** - Για production, ρυθμίστε custom domain
6. ⚠️ **Monitoring** - Παρακολουθήστε το dashboard για deliverability

**Καλή επιτυχία!** 🚀
