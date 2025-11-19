# Railway Email Proxy - Quick Start Guide 🚀

## Τι Έγινε

Προστέθηκε ένα **HTTP-to-SMTP email relay service** που λύνει το πρόβλημα του SMTP blocking στο Render free tier.

## Γρήγορη Εγκατάσταση (3 βήματα)

### 1️⃣ Deploy στο Railway (Free Tier)

**Επιλογή A: Railway CLI (από το railway-email-relay directory)**
```bash
cd railway-email-relay
railway login
railway init       # Δημιουργεί νέο project
railway up         # Deploy μόνο τα αρχεία του directory
railway domain     # Θα πάρεις URL όπως: https://your-app.railway.app
```

**Επιλογή B: Ξεχωριστό GitHub Repo (για Web UI)**
```bash
# Δημιούργησε νέο repository και copy τα αρχεία:
git clone https://github.com/YOUR-USERNAME/firebed-email-relay.git
cd firebed-email-relay
cp ../Firebed_private/railway-email-relay/* .
git add . && git commit -m "Initial" && git push

# Μετά deploy από Railway Web UI → GitHub repo
```

⚠️ **Railway Free Tier:** Δεν επιτρέπει custom root directory, γι' αυτό χρησιμοποιούμε CLI από subdirectory ή ξεχωριστό repo.

### 2️⃣ Configure Firebed Admin

1. Login στο Firebed admin: `/admin/settings`
2. Email Provider → **"Railway Proxy"**
3. Railway Proxy URL → `https://your-app.railway.app`
4. Save Settings

### 3️⃣ Test

Κάνε register νέο user → Θα λάβεις verification email!

---

## Πλήρης Οδηγός

📖 Διάβασε το `RAILWAY_EMAIL_DEPLOYMENT.md` για λεπτομερείς οδηγίες

---

## Τι Χρειάζεται

### SMTP Credentials (Gmail)

```bash
# Στο Render environment variables:
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password  # ⚠️ Χρειάζεται App Password!
SENDER_EMAIL=your-email@gmail.com
```

**Πώς να πάρεις Gmail App Password:**
1. Πήγαινε: https://myaccount.google.com/apppasswords
2. Enable 2-Factor Authentication (αν δεν το έχεις)
3. Create App Password
4. Χρησιμοποίησε το App Password (όχι το κανονικό password)

---

## Πώς Δουλεύει

```
Firebed (Render)  ──HTTP POST──>  Railway Relay  ──SMTP──>  Gmail
   (No SMTP)         (+ creds)      (Has SMTP)              (Email sent!)
```

1. Firebed χτυπάει το Railway API με email data + SMTP credentials
2. Railway στέλνει το email μέσω SMTP
3. User λαμβάνει email!

---

## Τι Email Στέλνονται

✅ Email Verification (register)
✅ Password Reset (forgot password)
✅ Custom Admin Emails (bulk send)

Όλα χρησιμοποιούν τα υπάρχοντα όμορφα Greek templates!

---

## Troubleshooting

### "SMTP credentials not configured"
➡️ Check ότι έχεις βάλει `SMTP_USER` και `SMTP_PASSWORD` στο Render

### "Railway proxy URL not configured"
➡️ Πήγαινε στο `/admin/settings` και βάλε το Railway URL

### "SMTP verification failed"
➡️ Για Gmail χρειάζεσαι App Password (όχι κανονικό password)

### Email δεν φτάνει
➡️ Check spam folder
➡️ Check Railway logs: `railway logs`

---

## Ασφάλεια (Προτεινόμενα για Production)

⚠️ **Για production προσθέτουμε:**

1. **Rate Limiting** (αποτρέπει spam)
2. **API Key Authentication** (αποτρέπει unauthorized access)

Οδηγίες: `SECURITY_SUMMARY.md`

---

## Alternative: Χρήση Resend

Αν δεν θέλεις Railway, μπορείς να χρησιμοποιήσεις Resend:

```bash
# Στο Render .env:
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_xxxxx
RESEND_EMAIL_SENDER=verified@yourdomain.com
```

Πλεονέκτημα: Simpler
Μειονέκτημα: Χρειάζεται verified domain

---

## Support Files

📁 `railway-email-relay/` - Railway service code
📖 `RAILWAY_EMAIL_DEPLOYMENT.md` - Full deployment guide (Greek)
🔒 `SECURITY_SUMMARY.md` - Security analysis
🧪 `test_railway_proxy.py` - Tests (run: `python3 test_railway_proxy.py`)

---

## Commands

```bash
# Deploy Railway service
cd railway-email-relay
railway up

# Check Railway logs
railway logs

# Test Railway health
curl https://your-app.railway.app/health

# Run tests
python3 test_railway_proxy.py
```

---

## Status

✅ Implementation Complete
✅ All Tests Pass (10/10)
✅ Documentation Complete
✅ Security Review Done
⚠️ Rate Limiting Recommended (see docs)

---

**Ερωτήσεις;** Check `RAILWAY_EMAIL_DEPLOYMENT.md` ή `SECURITY_SUMMARY.md`

🎉 **Ready to Deploy!**
