# Railway Email Proxy - Deployment Guide

## Περιγραφή

Αυτός ο οδηγός εξηγεί πώς να κάνεις deploy το Railway email relay service και πώς να το συνδέσεις με το Firebed_private app που τρέχει στο Render.

## Πρόβλημα που Λύνει

Το Render free tier **μπλοκάρει SMTP outbound connections**, άρα το Firebed_private δεν μπορεί να στείλει emails απευθείας μέσω SMTP.

## Λύση

Χρησιμοποιούμε ένα **HTTP-to-SMTP proxy service** που:
1. Τρέχει στο Railway (ή άλλο platform που επιτρέπει SMTP)
2. Δέχεται HTTP POST requests από το Firebed_private
3. Στέλνει τα emails μέσω SMTP

## Architecture

```
┌─────────────────┐         HTTP          ┌──────────────────┐        SMTP         ┌──────────────┐
│  Firebed_private│    ────────────────>   │ Railway Email    │   ───────────────>  │ SMTP Server  │
│  (Render)       │    JSON with email     │ Relay Service    │   Send actual email │ (Gmail, etc) │
│  No SMTP access │    + SMTP credentials  │ (Railway)        │                     │              │
└─────────────────┘                        └──────────────────┘                     └──────────────┘
```

---

## Βήμα 1: Deploy Railway Email Relay Service

### Επιλογή A: Deploy με Railway CLI (Προτεινόμενο)

1. **Install Railway CLI:**
   ```bash
   npm install -g @railway/cli
   ```

2. **Login στο Railway:**
   ```bash
   railway login
   ```
   Θα ανοίξει browser για authentication.

3. **Navigate στο directory:**
   ```bash
   cd railway-email-relay
   ```

4. **Initialize Railway project:**
   ```bash
   railway init
   ```
   - Επίλεξε "Create a new project"
   - Δώσε ένα όνομα (π.χ. "email-relay-firebed")

5. **Deploy:**
   ```bash
   railway up
   ```

6. **Generate domain:**
   ```bash
   railway domain
   ```
   Θα σου δώσει ένα URL όπως: `https://email-relay-firebed.railway.app`

### Επιλογή B: Deploy μέσω Railway Web UI

1. Πήγαινε στο https://railway.app και κάνε login

2. Κάνε click "New Project" → "Deploy from GitHub repo"

3. Επίλεξε το repository `douradonis/Firebed_private`

4. Στα **Project Settings**:
   - **Root Directory**: `railway-email-relay`
   - **Build Command**: (leave empty, will auto-detect)
   - **Start Command**: `npm start`

5. Κάνε deploy - το Railway θα detect αυτόματα το `package.json` και θα εγκαταστήσει dependencies

6. Στο **Settings** → **Networking**, κάνε **Generate Domain** για να πάρεις public URL

---

## Βήμα 2: Test το Railway Service

Μόλις κάνει deploy, test ότι λειτουργεί:

### Health Check
```bash
curl https://YOUR-APP.railway.app/health
```

**Expected response:**
```json
{
  "status": "ok",
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

### Test Email Send

**ΣΗΜΑΝΤΙΚΟ:** Για Gmail χρειάζεσαι [App Password](https://support.google.com/accounts/answer/185833).

```bash
curl -X POST https://YOUR-APP.railway.app/send-mail \
  -H "Content-Type: application/json" \
  -d '{
    "smtp": {
      "host": "smtp.gmail.com",
      "port": 587,
      "secure": false,
      "user": "YOUR-EMAIL@gmail.com",
      "pass": "YOUR-APP-PASSWORD"
    },
    "mail": {
      "from": "YOUR-EMAIL@gmail.com",
      "to": "RECIPIENT@example.com",
      "subject": "Test από Railway",
      "text": "Αυτό είναι test!",
      "html": "<h1>Test Email</h1><p>Success!</p>"
    }
  }'
```

**Expected success response:**
```json
{
  "success": true,
  "messageId": "<unique-id@mail.gmail.com>",
  "accepted": ["recipient@example.com"],
  "rejected": [],
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

---

## Βήμα 3: Configure Firebed_private

### 3.1: Σύνδεση στο Admin Panel

1. Πήγαινε στο Firebed_private admin panel:
   ```
   https://your-firebed-app.onrender.com/admin/settings
   ```

2. Login ως admin

### 3.2: Configure Email Settings

1. Στο **Email Provider** dropdown:
   - Επίλεξε **"Railway Proxy (HTTP-to-SMTP Relay)"**

2. Στο **Railway Proxy URL** field:
   - Βάλε το Railway URL που πήρες (π.χ. `https://email-relay-firebed.railway.app`)

3. Κάνε **Save Settings**

### 3.3: Ensure SMTP Credentials are Set

Το Railway proxy χρειάζεται SMTP credentials για να στείλει emails. Βεβαιώσου ότι έχεις set στο Render (ή στο `.env`):

```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SENDER_EMAIL=your-email@gmail.com
```

**Για Gmail:**
- Enable 2-Factor Authentication
- Generate App Password: https://myaccount.google.com/apppasswords
- Χρησιμοποίησε το App Password αντί για κανονικό password

---

## Βήμα 4: Test Email Sending από Firebed_private

### 4.1: Test με Admin Panel

1. Πήγαινε στο `/admin/settings`
2. Scroll down, θα δεις "Test Email" button (αν υπάρχει)
3. Κάνε test αποστολή

### 4.2: Test με User Registration

1. Δημιούργησε νέο user account
2. Θα πρέπει να λάβεις verification email
3. Check το inbox (και spam folder)

### 4.3: Test με Password Reset

1. Πήγαινε στο forgot password page
2. Βάλε το email σου
3. Θα πρέπει να λάβεις password reset email

---

## Troubleshooting

### Πρόβλημα: "Railway proxy URL not configured"

**Λύση:**
- Check ότι έχεις βάλει σωστά το Railway URL στο admin settings
- Ή βάλε το στο `.env`: `RAILWAY_PROXY_URL=https://your-app.railway.app`

### Πρόβλημα: "SMTP credentials not configured"

**Λύση:**
- Βεβαιώσου ότι έχεις set `SMTP_USER` και `SMTP_PASSWORD` στο Render environment variables
- Για Gmail χρειάζεσαι App Password, όχι κανονικό password

### Πρόβλημα: "Railway proxy request timeout"

**Λύση:**
- Check ότι το Railway service τρέχει: `curl https://your-app.railway.app/health`
- Check Railway logs για errors
- Βεβαιώσου ότι δεν έχεις typo στο URL

### Πρόβλημα: "SMTP verification failed"

**Λύση:**
- Check SMTP credentials (user, password)
- Για Gmail: enable "App Password"
- Για Outlook: enable "Allow less secure apps"
- Check ότι το SMTP server/port είναι σωστά

### Πρόβλημα: Email δεν φτάνει

**Λύση:**
- Check spam folder
- Check Railway logs: `railway logs`
- Verify ότι το sender email είναι verified
- Για production, χρησιμοποίησε dedicated email service (Mailgun, SendGrid)

---

## Email Templates που Υποστηρίζονται

Το Railway proxy υποστηρίζει **όλα** τα email templates που υπάρχουν στο Firebed_private:

1. ✅ **Email Verification** - Όταν κάνεις register νέο account
2. ✅ **Password Reset** - Όταν ξεχάσεις τον κωδικό
3. ✅ **Custom Admin Emails** - Bulk emails από admin panel

Όλα χρησιμοποιούν τα ίδια όμορφα HTML templates που ήδη υπάρχουν.

---

## Ασφάλεια & Best Practices

### 🔒 Προσοχή με Credentials

**ΣΗΜΑΝΤΙΚΟ:** Το Railway proxy στέλνει SMTP credentials με κάθε request. Αυτό σημαίνει:

1. **HTTPS Only**: Βεβαιώσου ότι το Railway URL είναι HTTPS
2. **Trusted Network**: Μην το expose publicly αν είναι production
3. **API Key Authentication**: Προσθήκη authentication στο proxy (optional)

### Προσθήκη API Key Authentication (Προτεινόμενο)

Edit το `railway-email-relay/server.js`:

```javascript
// At the top
const API_KEY = process.env.API_KEY || 'change-me-in-production';

// Add middleware before /send-mail route
app.use('/send-mail', (req, res, next) => {
    const authHeader = req.headers['authorization'];
    if (!authHeader || authHeader !== `Bearer ${API_KEY}`) {
        return res.status(401).json({ success: false, error: 'Unauthorized' });
    }
    next();
});
```

Στο Railway, set environment variable:
```
API_KEY=your-super-secret-key-here
```

Στο Firebed_private `email_utils.py`, update το `send_railway_proxy_email`:

```python
headers = {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {os.getenv("RAILWAY_API_KEY", "")}'
}
response = requests.post(proxy_url, json=payload, timeout=30, headers=headers)
```

---

## Monitoring & Logs

### Railway Logs

Δες τα logs του proxy service:

```bash
railway logs
```

Ή στο Railway web UI: **Project** → **Deployments** → **Logs**

### Firebed Logs

Check τα logs στο Render:
- Render Dashboard → Your App → Logs
- Look for "Routing to Railway Proxy" messages

---

## Κόστος

### Railway Free Tier

- ✅ $5 free credit κάθε μήνα
- ✅ Αρκετό για email relay (low resource usage)
- ✅ No credit card required για trial

### Scaling

Αν χρειαστείς περισσότερα emails:
- Railway Pro: $5/μήνα
- Ή χρησιμοποίησε dedicated service (Resend, Mailgun, SendGrid)

---

## Alternative: Resend Email Service

Αν δεν θέλεις να διαχειριστείς Railway proxy, υπάρχει εναλλακτική:

### Χρησιμοποίησε Resend API

1. Πήγαινε στο https://resend.com (free tier: 100 emails/day)
2. Get API key
3. Στο Render `.env`:
   ```
   EMAIL_PROVIDER=resend
   RESEND_API_KEY=re_xxxxxxxxxxxxx
   RESEND_EMAIL_SENDER=verified@yourdomain.com
   ```
4. Save και restart

**Πλεονέκτημα:** No Railway needed, simpler setup
**Μειονέκτημα:** Χρειάζεσαι verified domain για production

---

## Support

Για ερωτήσεις:
1. Check Railway documentation: https://docs.railway.app
2. Check Nodemailer docs: https://nodemailer.com
3. Open issue στο GitHub repository

---

## Summary Checklist

- [ ] Deploy Railway email relay service
- [ ] Get Railway public URL
- [ ] Test Railway service με curl
- [ ] Configure Firebed admin settings με Railway URL
- [ ] Set SMTP credentials στο Render
- [ ] Test email verification
- [ ] Test password reset
- [ ] (Optional) Add API key authentication
- [ ] Monitor logs για errors

---

🎉 **Congratulations!** Το Firebed_private app μπορεί τώρα να στέλνει emails από το Render μέσω Railway proxy!
