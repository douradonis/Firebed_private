# Firebase & Encryption Setup Guide

## Prerequisites

- Firebase project (create at https://console.firebase.google.com)
- Python 3.8+
- pip

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This includes:
- `firebase-admin>=6.0` - Firebase Admin SDK
- `cryptography>=41.0` - Encryption library
- `pycryptodome>=3.18` - Additional crypto utilities

### 2. Firebase Setup

#### Create a Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Create a new project (or use existing)
3. Enable:
   - Authentication (Email/Password)
   - Realtime Database
   - Storage (optional, for backups)

#### Generate Service Account Key

1. In Firebase Console, go to **Project Settings** → **Service Accounts**
2. Click **Generate New Private Key**
3. Save the JSON file securely
4. Convert to base64 for environment variable:

```bash
cat firebase-key.json | base64 -w 0 > firebase_key_b64.txt
```

### 3. Environment Configuration

Create a `.env` file in the project root:

```env
# Flask Configuration
FLASK_SECRET=your-secret-key-change-me-in-production
FLASK_ENV=production

# Firebase Configuration
FIREBASE_CREDENTIALS_PATH=/path/to/firebase-key.json
FIREBASE_DATABASE_URL=https://your-project.firebaseio.com
FIREBASE_API_KEY=your-firebase-api-key

# Encryption Configuration
MASTER_ENCRYPTION_KEY=your-base64-encoded-fernet-key
ENCRYPTION_SALT=your-custom-salt-change-me

# Admin Configuration
ADMIN_USER_ID=1  # Set to the user ID of the admin account
```

#### Generate Encryption Key

```python
from encryption import generate_encryption_key
key = generate_encryption_key()
print(key)  # Use this value for MASTER_ENCRYPTION_KEY
```

### 4. Database Setup

Initialize the database:

```bash
python
>>> from app import app, db
>>> with app.app_context():
...     db.create_all()
...     print("Database initialized")
```

### 5. Create Admin User

```bash
python
>>> from app import app, db
>>> from models import User
>>> with app.app_context():
...     admin = User(username='admin')
...     admin.set_password('your-secure-password')
...     db.session.add(admin)
...     db.session.commit()
...     print(f"Admin created with ID: {admin.id}")
...     # Set ADMIN_USER_ID in .env to this ID
```

## Features

### Firebase Authentication

- User signup/login via Firebase Auth
- Email verification support
- Custom claims for role management
- Automatic sync with local SQLite DB

### Data Encryption

- **Master Key**: One key for all data (default)
- **Per-Group Keys**: Optional per-group encryption (advanced)
- Uses Fernet (symmetric encryption)
- PBKDF2 key derivation

### Admin Panel

Access admin panel at `/admin` (requires ADMIN_USER_ID user):

**Features:**
- 📊 System Dashboard (stats, recent activity)
- 👥 User Management (list, view, delete)
- 👨‍💼 Group Management (list, view, backup, delete)
- 📦 Backup/Restore (create backups, restore from backups)
- 📊 Activity Logs (traffic tracking, audit trail)
- 🔍 System Statistics (users, groups, data size)

**Routes:**
- `/admin` - Main dashboard
- `/admin/users` - User management
- `/admin/groups` - Group management
- `/admin/backups` - Backup management
- `/admin/activity-logs` - Activity tracking
- `/api/admin/*` - API endpoints (JSON)

## Firebase Realtime Database Structure

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

## Activity Logging

All actions are automatically logged to Firebase:

```python
from firebase_config import firebase_log_activity

firebase_log_activity(
    user_id=current_user.id,
    group_name="my_group",
    action="invoice_created",
    details={"invoice_id": 123, "amount": 100.50}
)
```

## Encryption Examples

### Encrypt Group Data

```python
from encryption import encrypt_data_with_group_key, decrypt_data_with_group_key

# Encrypt
data = {"invoices": [...], "summary": {...}}
encrypted = encrypt_data_with_group_key(data, group_key=None)  # Uses master key

# Decrypt
decrypted = decrypt_data_with_group_key(encrypted)
```

### Encrypt Files

```python
from encryption import encrypt_file, decrypt_file

# Encrypt
encrypt_file("/path/to/file.xlsx", "/path/to/file.xlsx.enc")

# Decrypt
decrypt_file("/path/to/file.xlsx.enc", "/path/to/file.xlsx")
```

## Backup & Recovery

### Manual Backup

```bash
curl -X POST http://localhost:5000/admin/groups/{group_id}/backup
```

Backups are stored in `/data/_backups/`

### Restore from Backup

```bash
curl -X POST http://localhost:5000/admin/backups/restore/{backup_name} \
  -d "group_id={group_id}"
```

## Security Best Practices

1. **Environment Variables**: Never commit `.env` to git
2. **Master Key**: Store securely (use AWS Secrets Manager, Azure Key Vault, etc.)
3. **Admin Account**: Use strong password, enable 2FA
4. **Firebase Security Rules**: Configure appropriately:

```json
{
  "rules": {
    "groups": {
      ".read": "root.child('users').child(auth.uid).exists()",
      ".write": "false"
    },
    "activity_logs": {
      ".read": "root.child('admins').child(auth.uid).exists()",
      ".write": "true"
    }
  }
}
```

5. **HTTPS**: Always use HTTPS in production
6. **Rate Limiting**: Implement rate limiting for API endpoints
7. **Audit Trail**: Regularly review activity logs

## Troubleshooting

### Firebase Connection Issues

```python
from firebase_config import init_firebase, is_firebase_enabled
init_firebase()
print(is_firebase_enabled())
```

### Encryption Errors

- Ensure `MASTER_ENCRYPTION_KEY` is set and valid
- Check key format (should be base64-encoded Fernet key)
- Verify `ENCRYPTION_SALT` matches key derivation

### Admin Access Denied

- Verify `ADMIN_USER_ID` in `.env` matches admin user ID
- Check `current_user.is_authenticated` is True
- Verify user ID in database

## API Endpoints

### Admin API

**Get System Stats**
```bash
GET /api/admin/stats
```

**List Users**
```bash
GET /api/admin/users
```

**List Groups**
```bash
GET /api/admin/groups
```

**Get Activity Logs**
```bash
GET /api/admin/activity-logs?group=group_name&limit=100
```

All admin endpoints require authentication and `ADMIN_USER_ID` match.

## Migration from Old System

If migrating from non-Firebase system:

1. Keep existing SQLite DB (for local user records)
2. Sync Firebase users with local users during login
3. Encrypt existing data with master key
4. Set up activity logging going forward
5. Create initial backups

## Support

For issues or questions:
- Check Firebase documentation: https://firebase.google.com/docs
- Check cryptography docs: https://cryptography.io/
- Review logs in `/data/activity.log` and Firebase Realtime DB

## License

Same as main project
