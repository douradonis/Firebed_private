# 🚀 Render Deployment - Quick Guide

## ✅ Email Verification Links - Έτοιμο για Production!

### 🎯 Τι Έχουμε Λύσει:

**❌ Προηγούμενο Πρόβλημα:**
- Hardcoded `localhost` URLs στα verification emails
- Links δεν δούλευαν στο Render production

**✅ Νέα Λύση:**
- **Dynamic Base URL Detection**
- **Αυτόματη προσαρμογή** σε κάθε environment
- **Zero configuration** για Render deployment

### 🔧 Πώς Λειτουργεί:

```python
def get_base_url():
    # 1. Flask Request Context (αυτόματο detection)
    if request.url_root:
        return request.url_root
    
    # 2. Render External URL (αυτόματο από Render)
    if RENDER_EXTERNAL_URL:
        return RENDER_EXTERNAL_URL
    
    # 3. Custom APP_URL (manual override)
    if APP_URL != localhost:
        return APP_URL
        
    # 4. Localhost fallback
    return "http://localhost:5000"
```

### 📋 Render Deployment Steps:

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Dynamic email URLs ready for production"
   git push origin main
   ```

2. **Create Render Web Service:**
   - Connect GitHub repository
   - Use `Dockerfile` για build
   - Set region (suggest Europe for Greek users)

3. **Environment Variables (Render Dashboard):**
   ```bash
   # Firebase
   FIREBASE_CREDENTIALS_PATH=firebase-key.json
   FIREBASE_DATABASE_URL=your-firebase-url
   FIREBASE_API_KEY=your-api-key
   
   # Email (Gmail)
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-gmail@gmail.com
   SMTP_PASSWORD=your-app-password
   SENDER_EMAIL=your-gmail@gmail.com
   
   # Security
   FLASK_SECRET=your-secure-secret
   MASTER_ENCRYPTION_KEY=your-encryption-key
   ENCRYPTION_SALT=your-salt
   
   # ⚠️ ΜΗΝ βάλεις APP_URL - το Render το κάνει αυτόματα!
   ```

4. **Upload Firebase Key:**
   - Upload `firebase-key.json` στο Render
   - Ή copy-paste το περιεχόμενο ως environment variable

### 🌐 URL Examples:

| Environment | Base URL | Email Link |
|-------------|----------|------------|
| **Development** | `http://localhost:5000` | `http://localhost:5000/firebase-auth/verify-email?token=...` |
| **Render** | `https://your-app.onrender.com` | `https://your-app.onrender.com/firebase-auth/verify-email?token=...` |
| **Custom Domain** | `https://firebed.gr` | `https://firebed.gr/firebase-auth/verify-email?token=...` |

### ✅ Testing Checklist:

**Μετά το deployment:**

1. **Signup Test:**
   - Πήγαινε στο `https://your-app.onrender.com/firebase-auth/signup`
   - Κάνε signup με το email σου
   - Check το inbox για verification email

2. **Link Verification:**
   - Το email link πρέπει να είναι: `https://your-app.onrender.com/firebase-auth/verify-email?token=...`
   - **ΌΧΙ** `localhost`!

3. **Password Reset Test:**
   - Δοκίμασε forgot password
   - Check ότι το reset link είναι production URL

### 🔧 Custom Domain (Optional):

Αν θέλεις custom domain όπως `firebed.gr`:

1. **Configure στο Render:**
   - Add custom domain στο dashboard
   - Set DNS records

2. **Set Environment Variable:**
   ```bash
   APP_URL=https://firebed.gr
   ```

### 🐛 Troubleshooting:

**Αν τα email links δεν δουλεύουν:**

1. **Check Logs:**
   ```bash
   # Στο Render dashboard, δες τα logs για:
   Using Flask request base URL: https://your-app.onrender.com
   ```

2. **Manual Override:**
   ```bash
   # Set στο Render environment:
   APP_URL=https://your-app.onrender.com
   ```

3. **Test URL Detection:**
   ```bash
   # Create test route να δεις το detected URL:
   @app.route('/test-url')
   def test_url():
       return FirebedEmailVerification.get_base_url()
   ```

### 🎉 Τι Περιμένεις να Δεις:

**✅ Working Production Emails:**
- Subject: "🔥 Επιβεβαίωση Email - Firebed Account"
- Beautiful Greek HTML template
- Working verification link με production domain
- Professional branding

**✅ Working Password Reset:**
- Subject: "🔐 Επαναφορά Κωδικού - Firebed"
- Secure reset link με production domain
- Greek language interface

**✅ Zero Configuration:**
- Τίποτα hardcoded
- Αυτόματη προσαρμογή σε κάθε environment
- Future-proof για domain changes

## 📱 Mobile QR/OCR Scanner Feature

### ✨ New Feature: QR και OCR Scanning από Mobile

**Τι Προστέθηκε:**
- Toggle switch QR/OCR στην mobile συσκευή (μόνο για τιμολόγια)
- Live OCR scanning με Tesseract.js για εξαγωγή 15ψήφιου MARK
- Πλήρης συγχρονισμός PC ↔️ Mobile για όλα τα toggles (mode, repeat, auto-submit)

**Τεχνικά Χαρακτηριστικά:**
1. **Client-Side OCR**: Χρησιμοποιεί Tesseract.js (JavaScript library)
   - Δεν χρειάζεται server-side OCR engine
   - Κατάλληλο για Render Free Tier (χωρίς επιπλέον CPU/memory)
   - Υποστηρίζει Ελληνικά + Αγγλικά

2. **Separate OCR Module**: `static/mobile_ocr_scanner.js`
   - Καθαρός, επαναχρησιμοποιήσιμος κώδικας
   - Class-based architecture
   - Clean API με callbacks

3. **Smart Mode Switching**:
   - QR/OCR toggle εμφανίζεται μόνο όταν είναι επιλεγμένα τα Τιμολόγια
   - Αυτόματη εναλλαγή scanners κατά την αλλαγή mode
   - Προστασία από memory leaks με proper cleanup

**Render Compatibility:**
- ✅ Δεν χρειάζονται επιπλέον system dependencies
- ✅ Όλη η επεξεργασία OCR γίνεται στο browser
- ✅ Minimal server load
- ✅ Free tier friendly

**Browser Requirements:**
- Modern browser με WebRTC support
- Camera access permissions
- JavaScript enabled

### 📞 Support:

Αν χρειάζεσαι βοήθεια:
1. Check τα Render logs
2. Test το `/test-url` endpoint
3. Verify environment variables
4. Check email SMTP settings
5. Verify camera permissions στο mobile device

**Όλα είναι έτοιμα για production! 🚀**