# 🔐 Firebed Private - Enterprise Admin & Encryption Features

> End-to-end encrypted data management with centralized admin panel

## 🎯 What's New

### Firebase Integration ✨
- **Firebase Realtime Database** for encrypted cloud storage
- **Activity logging** with complete audit trail
- **Traffic tracking** to monitor all user actions
- **Automatic backups** before critical operations

### Encryption 🔒
- **Fernet encryption** (AES-128-CBC) for data at rest
- **Master encryption key** for all group data
- **Per-group encryption** support (advanced)
- **Automatic key derivation** using PBKDF2

### Admin Panel 👑
- **User management** - List, view, delete users
- **Group management** - List, view, backup, delete groups
- **Backup & restore** - Create/restore group backups
- **Activity logs** - Complete audit trail & traffic monitoring
- **System statistics** - User count, group count, data size

## 🚀 Quick Start

### 1. Setup Firebase (5 min)
See [FIREBASE_PROJECT_SETUP.md](./FIREBASE_PROJECT_SETUP.md)

```bash
# Create Firebase project
# Download service account key
# Set environment variables
```

### 2. Install & Configure (5 min)
```bash
pip install -r requirements.txt

# Create .env file (see .env.example)
# Generate encryption key: python -c "from encryption import generate_encryption_key; print(generate_encryption_key())"
```

### 3. Initialize (2 min)
```bash
python app.py

# Create admin user at http://localhost:5000
# Set ADMIN_USER_ID in .env to admin user ID
# Login and access /admin
```

### 4. Start Using
- Login as admin
- Click ⚙️ Admin in navigation
- Manage users, groups, backups, and activity

**Detailed guide**: [QUICKSTART.md](./QUICKSTART.md)

## 📋 Documentation

| Document | Purpose |
|----------|---------|
| [QUICKSTART.md](./QUICKSTART.md) | 5-minute setup guide |
| [FIREBASE_PROJECT_SETUP.md](./FIREBASE_PROJECT_SETUP.md) | Firebase console setup |
| [FIREBASE_SETUP.md](./FIREBASE_SETUP.md) | Technical Firebase details |
| [ADMIN_PANEL.md](./ADMIN_PANEL.md) | Admin features & API |
| [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) | Technical implementation |

## 🎛️ Admin Panel Features

### Dashboard (`/admin`)
- System statistics (users, groups, data size)
- Recent activity summary
- Quick navigation to all features
- Traffic overview

### Users (`/admin/users`)
- List all users
- View user details
- See group memberships
- Delete users

### Groups (`/admin/groups`)
- List all groups
- View group members
- Monitor group size
- Backup/delete groups

### Backups (`/admin/backups`)
- View all backups
- Create manual backups
- Restore from backups
- Auto-backup on deletion

### Activity Logs (`/admin/activity-logs`)
- View all user actions
- Filter by group
- Track traffic
- Audit trail

## 🔐 Security

### Encryption
```python
# Data encrypted at rest with Fernet
from encryption import encrypt_data, decrypt_data
encrypted = encrypt_data({"sensitive": "data"})
decrypted = decrypt_data(encrypted)
```

### Admin Access
```python
# Only accessible to ADMIN_USER_ID
@app.route('/admin')
@login_required
@_require_admin  # Checks ADMIN_USER_ID
def admin_dashboard():
    ...
```

### Activity Tracking
```python
# All actions logged to Firebase
firebase_log_activity(
    user_id=1,
    group_name="my_group",
    action="invoice_created",
    details={"id": 123}
)
```

## 📊 API Endpoints

### Admin JSON APIs

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
GET /api/admin/activity-logs?group=name&limit=100
```

All endpoints require admin authentication and return JSON.

## 🗂️ Project Structure

```
firebed/
├── app.py                      # Main Flask app + admin routes
├── models.py                   # Database models
├── auth.py                     # Authentication
├── firebase_config.py          # Firebase setup & helpers ✨ NEW
├── encryption.py               # Encryption utilities ✨ NEW
├── admin_panel.py              # Admin logic ✨ NEW
│
├── templates/
│   ├── base.html              # (Updated with admin nav)
│   └── admin/                  # ✨ NEW Admin templates
│       ├── dashboard.html
│       ├── users.html
│       ├── groups.html
│       ├── backups.html
│       └── activity_logs.html
│
├── data/
│   ├── firebed.db             # SQLite database
│   ├── _backups/              # ✨ NEW Backup storage
│   └── {group_name}/          # Per-group folders
│
├── .env.example               # ✨ NEW Environment template
├── QUICKSTART.md              # ✨ NEW Quick start guide
├── FIREBASE_PROJECT_SETUP.md  # ✨ NEW Firebase setup
├── FIREBASE_SETUP.md          # ✨ NEW Firebase details
├── ADMIN_PANEL.md             # ✨ NEW Admin guide
└── IMPLEMENTATION_SUMMARY.md  # ✨ NEW Technical summary
```

## 🔧 Configuration

### Required Environment Variables

```env
# Firebase
FIREBASE_CREDENTIALS_PATH=/path/to/firebase-key.json
FIREBASE_DATABASE_URL=https://project.firebaseio.com
FIREBASE_API_KEY=your-api-key

# Encryption
MASTER_ENCRYPTION_KEY=base64-fernet-key
ENCRYPTION_SALT=custom-salt

# Admin
ADMIN_USER_ID=1

# Flask
FLASK_SECRET=your-secret-key
```

See `.env.example` for all options.

## 🚢 Deployment

### Environment Setup
```bash
# Export environment variables (instead of .env file)
export FIREBASE_CREDENTIALS_PATH=/path/to/key.json
export FIREBASE_DATABASE_URL=https://project.firebaseio.com
export MASTER_ENCRYPTION_KEY=your-key
export ADMIN_USER_ID=1
```

### Production Checklist
- [ ] Strong `FLASK_SECRET`
- [ ] Generated `MASTER_ENCRYPTION_KEY`
- [ ] Firebase security rules configured
- [ ] HTTPS enabled
- [ ] Database backed up
- [ ] Admin created and verified
- [ ] Backup system tested

### Cloud Platforms
Works with any Python hosting:
- **Heroku**: Config Vars for environment
- **Render**: Environment tab
- **AWS/GCP/Azure**: Secret Manager

## 🧪 Testing

### Test Encryption
```python
from encryption import encrypt_data, decrypt_data
data = {"test": "value"}
encrypted = encrypt_data(data)
assert decrypt_data(encrypted) == data
```

### Test Firebase
```python
from firebase_config import is_firebase_enabled
assert is_firebase_enabled() == True
```

### Test Admin Panel
1. Set `ADMIN_USER_ID=1`
2. Login as user with ID 1
3. Navigate to `/admin`
4. Should see admin dashboard

## 🆘 Troubleshooting

### Firebase Not Connecting
```python
from firebase_config import init_firebase, is_firebase_enabled
init_firebase()
print(is_firebase_enabled())
```

### Encryption Errors
- Verify `MASTER_ENCRYPTION_KEY` is base64
- Check `ENCRYPTION_SALT` is set
- Run: `python -c "from encryption import generate_encryption_key; print(generate_encryption_key())"`

### Admin Panel Not Showing
- Verify `ADMIN_USER_ID` in `.env`
- Check user ID matches in database
- Restart app after changing ADMIN_USER_ID

See full troubleshooting in `ADMIN_PANEL.md`.

## 📈 Features by User Type

### Regular Users
- Upload/download documents
- Track fiscal data
- Generate reports
- Access group-specific data

### Admin Users
- See `/admin` panel
- Manage users & groups
- Create/restore backups
- Monitor activity & traffic
- View system statistics

### Data
- All data encrypted with master key
- Automatic backups before deletion
- Complete audit trail in Firebase
- Traffic logging for compliance

## 🔗 Quick Links

- **Admin Dashboard**: `/admin`
- **Users Management**: `/admin/users`
- **Groups Management**: `/admin/groups`
- **Backups**: `/admin/backups`
- **Activity Logs**: `/admin/activity-logs`
- **API Stats**: `/api/admin/stats`

## 📞 Support

- **Quick Start**: [QUICKSTART.md](./QUICKSTART.md)
- **Firebase Setup**: [FIREBASE_PROJECT_SETUP.md](./FIREBASE_PROJECT_SETUP.md)
- **Admin Guide**: [ADMIN_PANEL.md](./ADMIN_PANEL.md)
- **Technical**: [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md)

## 📄 License

Same as main project

---

## ✨ What's Included

```
✅ Firebase Admin SDK integration
✅ Fernet encryption (AES-128)
✅ Complete admin panel
✅ User & group management
✅ Backup & restore system
✅ Activity logging & audit trail
✅ System statistics
✅ API endpoints
✅ 6 new documentation files
✅ Security best practices
✅ Production-ready code
```

## 🎓 Next Steps

1. Read [QUICKSTART.md](./QUICKSTART.md) - Get running in 5 minutes
2. Read [FIREBASE_PROJECT_SETUP.md](./FIREBASE_PROJECT_SETUP.md) - Setup Firebase
3. Create admin user and test admin panel
4. Review security rules in Firebase Console
5. Set up backup schedule
6. Monitor activity logs

---

**Version**: 1.0  
**Status**: ✅ Production Ready  
**Last Updated**: November 14, 2024
