# 🚀 Firebed Deployment Guide

## Email Verification URLs - Dynamic Configuration

### 📋 Πώς λειτουργούν τα verification links

Το Firebed χρησιμοποιεί δυναμικό URL detection για να εξασφαλίσει ότι τα email verification links θα λειτουργούν σε όλα τα environments:

1. **Flask Request Context** (Προτεραιότητα 1)
   - Αυτόματα detect από το incoming request
   - Λειτουργεί για όλα τα domains

2. **Render External URL** (Προτεραιότητα 2)
   - Χρησιμοποιεί την `RENDER_EXTERNAL_URL` environment variable
   - Αυτόματα available στο Render

3. **Custom APP_URL** (Προτεραιότητα 3)
   - Από το `.env` αρχείο ή environment variables
   - Για custom domains

4. **Localhost Fallback** (Προτεραιότητα 4)
   - Development environment

## 🌐 Render Deployment

### Environment Variables που χρειάζονται:

```bash
# Firebase Configuration
FIREBASE_CREDENTIALS_PATH=firebase-key.json
FIREBASE_DATABASE_URL=your-firebase-db-url
FIREBASE_API_KEY=your-firebase-api-key

# Email Configuration  
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-gmail@gmail.com
SMTP_PASSWORD=your-app-password
SENDER_EMAIL=your-gmail@gmail.com

# Security
FLASK_SECRET=your-secure-secret-key
MASTER_ENCRYPTION_KEY=your-encryption-key
ENCRYPTION_SALT=your-custom-salt

# Application (Optional - Render auto-detects)
# APP_URL will be automatically set from RENDER_EXTERNAL_URL
```

### 📝 Render Setup Steps:

1. **Deploy to Render**
   ```bash
   # Push to GitHub
   git push origin main
   
   # Connect to Render dashboard
   # Create new Web Service from GitHub repo
   ```

2. **Set Environment Variables**
   - Copy all variables από το `.env` αρχείο
   - Paste στο Render dashboard Environment section
   - **Μην** set το `APP_URL` - το Render θα το κάνει αυτόματα

3. **Test Email Verification**
   - Signup με νέο account
   - Check email για verification link
   - Το link θα χρησιμοποιεί το Render domain αυτόματα

## 🔧 Custom Domain Setup

Αν χρησιμοποιείς custom domain:

```bash
# Set στο Render environment variables
APP_URL=https://yourdomain.com
```

## ✅ Testing Verification Links

### Local Testing:
```bash
# Τα links θα είναι: http://localhost:5000/firebase-auth/verify-email?token=...
python app.py
# Test signup and check email
```

### Production Testing:
```bash
# Τα links θα είναι: https://your-app.onrender.com/firebase-auth/verify-email?token=...
# Deploy to Render and test signup
```

## 🐛 Troubleshooting

### "This site can't be reached" Error:

1. **Check Base URL Detection**
   ```python
   from firebed_email_verification import FirebedEmailVerification
   print(FirebedEmailVerification.get_base_url())
   ```

2. **Render Environment Check**
   ```bash
   echo $RENDER_EXTERNAL_URL
   # Should show: https://your-app.onrender.com
   ```

3. **Manual Override**
   ```bash
   # Set στο Render dashboard
   APP_URL=https://your-app.onrender.com
   ```

### Email Links Not Working:

1. **Check Email Template**
   - Τα links πρέπει να είναι clickable
   - Ensure HTML email format

2. **Token Expiration**
   - Default: 24 hours
   - Check token creation timestamp

3. **Route Verification**
   ```bash
   # Check routes exist
   curl https://your-app.onrender.com/firebase-auth/verify-email?token=test
   ```

## 📱 Production Checklist

- [ ] Environment variables set στο Render
- [ ] Firebase key uploaded
- [ ] Email SMTP configured  
- [ ] Base URL detection working
- [ ] Signup flow tested
- [ ] Password reset tested
- [ ] Admin panel accessible

## 🔗 URL Examples

| Environment | Base URL | Verification Link |
|-------------|----------|-------------------|
| Local | `http://localhost:5000` | `http://localhost:5000/firebase-auth/verify-email?token=...` |
| Render | `https://myapp.onrender.com` | `https://myapp.onrender.com/firebase-auth/verify-email?token=...` |
| Custom | `https://firebed.gr` | `https://firebed.gr/firebase-auth/verify-email?token=...` |

Το σύστημα θα choose αυτόματα το σωστό URL για κάθε environment! 🎯