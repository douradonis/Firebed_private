# Firebed Private - Firebase & Encryption Setup Guide

## 📋 New Features

### 1. Firebase Integration
- **Firebase Authentication**: Users can sign up/login via Firebase
- **Realtime Database**: Encrypted data syncing to Firebase
- **Activity Tracking**: All user actions logged to Firebase for audit trails
- **Traffic Monitoring**: Track which users access which groups and when

### 2. Data Encryption
- **Master Encryption Key**: Encrypt all group data with a single master key
- **Per-Group Keys**: Optional per-group encryption keys (advanced)
- **File Encryption**: Encrypt/decrypt sensitive files
- **Automatic**: Data encrypted at rest in Firebase

### 3. Admin Panel
- **User Management**: List, view, and delete users
- **Group Management**: List, view, backup, and delete groups
- **Backup & Restore**: Create backups of group data, restore from backups
- **Activity Logs**: View all user activity and traffic
- **System Statistics**: Overview of system usage

## 🚀 Quick Start

### Prerequisites
```bash
# Create Firebase project at https://console.firebase.google.com
# Download service account key JSON
# Set environment variables (see below)
```

### Installation

1. **Install dependencies**:
```bash
pip install -r requirements.txt
```

2. **Set up environment variables** (create `.env` file):
```env
# Firebase
FIREBASE_CREDENTIALS_PATH=/path/to/firebase-key.json
FIREBASE_DATABASE_URL=https://your-project.firebaseio.com
FIREBASE_API_KEY=your-firebase-api-key

# Encryption
MASTER_ENCRYPTION_KEY=your-base64-fernet-key
ENCRYPTION_SALT=your-custom-salt

# Admin
ADMIN_USER_ID=1

# Flask
FLASK_SECRET=your-secret-key
```

3. **Generate encryption key** (if needed):
```bash
python -c "from encryption import generate_encryption_key; print(generate_encryption_key())"
```

4. **Initialize database**:
```bash
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

5. **Create admin user**:
```bash
python
 from app import app, db
 from models import User
 with app.app_context():
     admin = User(username='admin')
     admin.set_password('paradeisou16')
     db.session.add(admin)
     db.session.commit()
     print(f"Admin ID: {admin.id}")
```

6. **Update ADMIN_USER_ID** in `.env` with the admin user ID from step 5

7. **Run the app**:
```bash
python app.py
```

## 🔒 Security Features

### Encryption
- **Fernet**: Symmetric encryption (AES-128-CBC)
- **PBKDF2**: Key derivation with 100,000 iterations
- **Master Key**: Single key encrypts all data
- **Per-Group Keys**: Optional per-group encryption

### Firebase Security
- **Admin SDK**: Server-side authentication
- **Custom Claims**: Role-based access control
- **Activity Logs**: Complete audit trail
- **Encrypted Storage**: Data encrypted at rest

### Access Control
- **User Roles**: Admin/Member roles per group
- **Group Isolation**: Users can only access their groups
- **Admin Panel**: Only accessible to admin user
- **Rate Limiting**: Optional per API endpoint

## 👥 Admin Panel

### Access
- Navigate to `/admin` (admin-only, requires ADMIN_USER_ID)
- Dashboard shows system overview
- Quick access to users, groups, backups, activity logs

### User Management
- **List Users**: See all users and their groups
- **View Details**: See user information and group memberships
- **Delete User**: Remove user from system (and Firebase)

### Group Management
- **List Groups**: See all groups and member counts
- **View Details**: See group members, size, and creation date
- **Create Backup**: Create backup of group data
- **Delete Group**: Delete group and backup first

### Backup & Restore
- **Auto-Backup**: Groups are automatically backed up before deletion
- **Manual Backups**: Create backups anytime
- **Restore**: Restore group from backup
- **Storage**: Backups stored in `/data/_backups/`

### Activity Logs
- **Traffic Tracking**: See all user actions
- **Timestamps**: When each action occurred
- **Details**: Additional information about each action
- **Groups**: Filter logs by group
- **Export**: Download logs for analysis

## 📊 API Endpoints

### Admin APIs (JSON)

**Get System Statistics**
```bash
GET /api/admin/stats
```

**List All Users**
```bash
GET /api/admin/users
```

**List All Groups**
```bash
GET /api/admin/groups
```

**Get Activity Logs**
```bash
GET /api/admin/activity-logs?group=group_name&limit=100
```

All endpoints require:
- User authentication
- ADMIN_USER_ID match
- Returns JSON

## 🗄️ Firebase Database Structure

```
/
├── groups/
│   └── {group_name}/
│       ├── invoices/
│       ├── settings/
│       └── metadata/
├── activity_logs/
│   └── {group_name}/
│       └── {timestamp}/
│           ├── user_id
│           ├── action
│           ├── timestamp
│           └── details
└── users/
    └── {firebase_uid}/
        ├── email
        ├── username
        └── local_user_id
```

## 🔄 Activity Logging

### Logged Events
- User signup/login
- Group creation/deletion
- User added/removed from group
- Backup created/restored
- Data imported/exported
- User roles changed

### Usage Example
```python
from firebase_config import firebase_log_activity

firebase_log_activity(
    user_id=current_user.id,
    group_name="my_group",
    action="invoice_uploaded",
    details={
        "invoice_id": 123,
        "amount": 1500.50,
        "date": "2024-11-14"
    }
)
```

## 🔐 Encryption Examples

### Encrypt Dictionary
```python
from encryption import encrypt_data, decrypt_data

# Encrypt
data = {"name": "John", "vat": "123456789"}
encrypted = encrypt_data(data)

# Decrypt
decrypted = decrypt_data(encrypted)
```

### Encrypt Files
```python
from encryption import encrypt_file, decrypt_file

# Encrypt
encrypt_file("/path/to/data.xlsx", "/path/to/data.xlsx.enc")

# Decrypt
decrypt_file("/path/to/data.xlsx.enc", "/path/to/data.xlsx")
```

### Per-Group Encryption
```python
from encryption import encrypt_data_with_group_key, decrypt_data_with_group_key

# Encrypt with group key
encrypted = encrypt_data_with_group_key(data, group_key="group-specific-key")

# Decrypt
decrypted = decrypt_data_with_group_key(encrypted, group_key="group-specific-key")
```

## 🐛 Troubleshooting

### Firebase Connection Issues
```python
from firebase_config import init_firebase, is_firebase_enabled
init_firebase()
print(f"Firebase enabled: {is_firebase_enabled()}")
```

### Encryption Errors
- Verify `MASTER_ENCRYPTION_KEY` is valid base64
- Check `ENCRYPTION_SALT` is set
- Ensure key hasn't been corrupted

### Admin Access Denied
- Verify `ADMIN_USER_ID` in `.env`
- Check user exists in database
- Confirm user is authenticated

### Database Issues
```bash
# Reset database (BE CAREFUL!)
rm firebed.db
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

## 📚 File Structure

```
app.py                      # Main Flask app with admin routes
models.py                   # Database models (User, Group, etc)
auth.py                     # Authentication routes
firebase_config.py          # Firebase configuration & helpers
encryption.py               # Encryption/decryption utilities
admin_panel.py              # Admin panel backend logic

templates/
├── admin/
│   ├── dashboard.html      # Admin dashboard
│   ├── users.html          # User management
│   ├── user_detail.html    # User details
│   ├── groups.html         # Group management
│   ├── group_detail.html   # Group details
│   ├── backups.html        # Backup management
│   └── activity_logs.html  # Activity logs

FIREBASE_SETUP.md           # Detailed Firebase setup guide
```

## 🌐 Environment Variables Reference

```env
# Flask
FLASK_SECRET                # Secret key for sessions
FLASK_ENV                   # development/production
DEBUG                       # 0/1

# Firebase
FIREBASE_CREDENTIALS_PATH   # Path to service account JSON
FIREBASE_DATABASE_URL       # Realtime Database URL
FIREBASE_API_KEY           # Firebase API key

# Encryption
MASTER_ENCRYPTION_KEY      # Base64-encoded Fernet key
ENCRYPTION_SALT            # Custom salt for key derivation

# Admin
ADMIN_USER_ID              # ID of admin user

# Database
DATABASE_URL               # SQLite URL (default: sqlite:///firebed.db)

# Server
RENDER_EXTERNAL_URL        # External URL for deployed apps
PUBLIC_BASE_URL            # Public base URL

# MyData (if using)
AADE_USER_ID              # MyData user ID
AADE_SUBSCRIPTION_KEY     # MyData subscription key
MYDATA_ENV                # sandbox/production
```

## 🚢 Deployment

### Production Checklist
- [ ] Change `FLASK_SECRET` to a strong random value
- [ ] Set `FLASK_ENV=production`
- [ ] Generate new `MASTER_ENCRYPTION_KEY`
- [ ] Backup database before deploying
- [ ] Test Firebase connection
- [ ] Configure Firebase Security Rules
- [ ] Enable HTTPS
- [ ] Set up monitoring/alerting

### Cloud Deployment
Works well with:
- **Heroku**: Set environment variables in Config Vars
- **Render.com**: Set environment variables in Environment
- **AWS/GCP/Azure**: Use Secret Manager + environment variables

## 📞 Support

For detailed information, see:
- `FIREBASE_SETUP.md` - Complete Firebase setup guide
- Firebase Docs: https://firebase.google.com/docs
- Cryptography Docs: https://cryptography.io/

## 📄 License

Same as main project

---

**Created**: November 2024
**Version**: 1.0
