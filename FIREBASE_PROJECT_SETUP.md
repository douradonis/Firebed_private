# Firebase Project Setup Guide

## Step-by-Step Setup

### Step 1: Create Firebase Project

1. Go to https://console.firebase.google.com
2. Click "Add Project"
3. Enter project name (e.g., "firebed-private")
4. Accept terms and create project
5. Wait for project to initialize (1-2 minutes)

### Step 2: Enable Services

In Firebase Console:

1. **Enable Authentication**
   - Go to "Authentication" in left menu
   - Click "Get Started"
   - Enable "Email/Password" method
   - (Optional) Enable "Google", "GitHub", etc.

2. **Enable Realtime Database**
   - Go to "Realtime Database" in left menu
   - Click "Create Database"
   - Select region (closer to your users)
   - Choose "Start in test mode" (change security rules later)
   - Click "Enable"

3. **(Optional) Enable Cloud Storage**
   - Go to "Cloud Storage" in left menu
   - Click "Get Started"
   - Select region
   - Click "Done"

### Step 3: Get Project Credentials

1. Go to **Project Settings** (gear icon, top right)

2. Click **"Service Accounts"** tab

3. Click **"Generate New Private Key"**
   - Firebase will download a JSON file (e.g., `firebed-private-firebase-adminsdk-abc123.json`)
   - **IMPORTANT: Save this file securely!**

4. Copy these values from the JSON file:
   ```json
   {
     "project_id": "your-project-id",
     "private_key": "-----BEGIN PRIVATE KEY-----...",
     "private_key_id": "...",
     "client_email": "firebase-adminsdk-xxx@your-project-id.iam.gserviceaccount.com",
     ...
   }
   ```

5. Also get from **Project Settings** → **General**:
   - **Database URL**: Should be `https://your-project-id.firebaseio.com`
   - **API Key**: In "Your apps" section (or create a new web app to get it)

### Step 4: Configure Environment Variables

Create `.env` file in project root:

```env
# Path to Firebase service account JSON (downloaded in Step 3)
FIREBASE_CREDENTIALS_PATH=./firebase-key.json

# Firebase Realtime Database URL (from Project Settings)
FIREBASE_DATABASE_URL=https://your-project-id.firebaseio.com

# Firebase API Key (from Project Settings)
FIREBASE_API_KEY=your-web-api-key

# Encryption (generate with: python -c "from encryption import generate_encryption_key; print(generate_encryption_key())")
MASTER_ENCRYPTION_KEY=your-base64-fernet-key-here
ENCRYPTION_SALT=firebed-custom-salt

# Admin user ID
ADMIN_USER_ID=1

# Flask
FLASK_SECRET=your-super-secret-key-change-in-production
```

### Step 5: Save Firebase Key

1. Copy `firebase-key.json` to project root
   ```bash
   cp ~/Downloads/firebed-private-firebase-adminsdk-abc123.json ./firebase-key.json
   ```

2. **IMPORTANT**: Add to `.gitignore`:
   ```
   firebase-key.json
   .env
   *.pem
   ```

### Step 6: Test Connection

```bash
python << 'EOF'
import firebase_config
firebase_config.init_firebase()
if firebase_config.is_firebase_enabled():
    print("✅ Firebase connected successfully!")
else:
    print("❌ Firebase connection failed")
EOF
```

### Step 7: Configure Firebase Security Rules

**IMPORTANT: Test mode expires after 30 days**

In Firebase Console → Realtime Database:

1. Click **"Rules"** tab

2. Replace with:
```json
{
  "rules": {
    "groups": {
      "$uid": {
        ".read": "auth.uid != null",
        ".write": "root.child('admins').child(auth.uid).exists()",
        ".validate": "newData.hasChildren()"
      }
    },
    "activity_logs": {
      "$group": {
        ".read": "root.child('admins').child(auth.uid).exists()",
        ".write": "root.child('admins').child(auth.uid).exists()"
      }
    },
    "users": {
      "$uid": {
        ".read": "auth.uid === $uid || root.child('admins').child(auth.uid).exists()",
        ".write": "auth.uid === $uid || root.child('admins').child(auth.uid).exists()"
      }
    },
    ".read": false,
    ".write": false
  }
}
```

3. Click **"Publish"**

### Step 8: Initialize Admin SDK

```bash
python << 'EOF'
from app import app, db, firebase_config

with app.app_context():
    # Initialize Firebase
    firebase_config.init_firebase()
    
    # Create tables
    db.create_all()
    
    print("✅ Firebase and database initialized!")
EOF
```

## Testing Firebase Connection

### Test Authentication

```python
import firebase_config

# Test write
result = firebase_config.firebase_write_data('/test/hello', {'message': 'world'})
print(f"Write result: {result}")

# Test read
data = firebase_config.firebase_read_data('/test/hello')
print(f"Read result: {data}")

# Clean up
firebase_config.firebase_delete_data('/test')
```

### Test Activity Logging

```python
from firebase_config import firebase_log_activity, firebase_get_group_activity_logs

# Log activity
firebase_log_activity(1, "test_group", "test_action", {"test": "data"})

# Read logs
logs = firebase_get_group_activity_logs("test_group", limit=10)
print(f"Logs: {logs}")
```

## Common Issues

### Issue: "FIREBASE_CREDENTIALS_PATH not found"
**Solution**: 
- Verify path in `.env` is correct
- Check file exists: `ls -la firebase-key.json`
- Use absolute path if relative doesn't work

### Issue: "FIREBASE_DATABASE_URL not set"
**Solution**:
- Get from Firebase Console → Project Settings
- Should look like: `https://your-project-id.firebaseio.com`
- Make sure to include `https://` prefix

### Issue: "Permission denied" in logs
**Solution**:
- Security rules might be blocking
- Test with "Test mode" first (less restrictive)
- Check service account has Realtime Database admin role

### Issue: "Authentication required"
**Solution**:
- Firebase Auth might not be enabled
- Go to Authentication in Firebase Console
- Click "Get Started" and enable Email/Password

## Next Steps

1. ✅ Test Firebase connection
2. ✅ Configure security rules
3. ✅ Create first admin user
4. ✅ Test admin panel
5. ✅ Set up backups
6. ✅ Monitor activity logs

## Security Checklist

- [ ] Service account key stored safely (never commit)
- [ ] `.env` file in `.gitignore`
- [ ] Firebase security rules configured
- [ ] Test mode disabled before production
- [ ] API key restricted to your domain
- [ ] Backups enabled and tested
- [ ] Activity logs monitored

## Production Deployment

Before deploying to production:

1. **Change security rules** from test mode to restrictive
2. **Set strong FLASK_SECRET**
3. **Generate new MASTER_ENCRYPTION_KEY**
4. **Use environment variables** (not .env file)
5. **Enable Firebase authentication**
6. **Set up backups**
7. **Monitor activity logs**
8. **Use HTTPS only**

## Support

If you encounter issues:

1. Check Firebase Console logs
2. Enable debug logging in Python:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```
3. Review `firebase_config.py` error messages
4. Check `FIREBASE_SETUP.md` for detailed guide

---

**Quick Reference:**
- Firebase Console: https://console.firebase.google.com
- Firebase Docs: https://firebase.google.com/docs
- Realtime DB Docs: https://firebase.google.com/docs/database
- Auth Docs: https://firebase.google.com/docs/auth
