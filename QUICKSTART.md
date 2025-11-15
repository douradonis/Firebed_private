# ⚡ Quick Start Guide

## 🎯 In 5 Minutes

### 1. Get Firebase Credentials
```bash
# Go to https://console.firebase.google.com
# Create new project → Service Accounts → Generate Private Key
# Save as firebase-key.json
```

### 2. Generate Encryption Key
```bash
python -c "from encryption import generate_encryption_key; print(generate_encryption_key())"
# Copy output
```

### 3. Create `.env` File
```env
FIREBASE_CREDENTIALS_PATH=./firebase-key.json
FIREBASE_DATABASE_URL=https://your-project.firebaseio.com
FIREBASE_API_KEY=your-api-key
MASTER_ENCRYPTION_KEY=<paste-from-step-2>
FLASK_SECRET=your-secret-key
ADMIN_USER_ID=1
```

### 4. Setup Database
```bash
pip install -r requirements.txt
python << 'EOF'
from app import app, db
from models import User
with app.app_context():
    db.create_all()
    admin = User(username='admin')
    admin.set_password('your-password')
    db.session.add(admin)
    db.session.commit()
    print(f"Admin created with ID: {admin.id}")
EOF
```

### 5. Run App
```bash
python app.py
```

### 6. Access Admin Panel
- Go to `http://localhost:5000`
- Login as `admin`
- See ⚙️ Admin button in navigation
- Click to access admin panel

## 📋 What You Can Do

### 👥 User Management
- View all users
- See their groups
- Delete users

### 👨‍💼 Group Management
- View all groups
- See members
- Create backups
- Delete groups

### 📦 Backups
- Create manual backups
- Restore from backups
- See backup history

### 📊 Activity Logs
- View all user actions
- See who accessed what
- Track traffic
- Filter by group

## 🆘 Troubleshooting

### Firebase Connection Error
```python
from firebase_config import is_firebase_enabled
print(is_firebase_enabled())  # Should be True
```

### Admin Panel Not Showing
- Verify `ADMIN_USER_ID=1` in `.env`
- Verify you're logged in as user with ID 1
- Check user exists: `python -c "from models import User; from app import app; app.app_context().push(); print(User.query.get(1))"`

### Database Error
```bash
rm firebed.db
python app.py  # Will recreate
```

## 📚 Full Guides

- See `FIREBASE_SETUP.md` for detailed Firebase setup
- See `ADMIN_PANEL.md` for admin features guide
- See `IMPLEMENTATION_SUMMARY.md` for technical details

## 🎓 Usage Examples

### Encrypt Data
```python
from encryption import encrypt_data
data = {"invoice": 123, "amount": 100}
encrypted = encrypt_data(data)
```

### Log Activity
```python
from firebase_config import firebase_log_activity
firebase_log_activity(1, "my_group", "invoice_created", {"id": 123})
```

### List Users (Admin)
```python
from admin_panel import admin_list_all_users
users = admin_list_all_users()
for u in users:
    print(u['username'], u['groups'])
```

## ✅ Checklist

- [ ] Firebase project created
- [ ] Service account key downloaded
- [ ] `.env` file configured
- [ ] Encryption key generated
- [ ] Dependencies installed
- [ ] Database initialized
- [ ] Admin user created
- [ ] App runs without errors
- [ ] Can login as admin
- [ ] Admin panel visible
- [ ] Can see users/groups in admin

## 🚀 Next Steps

1. Read `FIREBASE_SETUP.md` for complete setup
2. Explore admin panel features
3. Set up Firebase Security Rules
4. Configure backup schedules
5. Monitor activity logs regularly

## 💡 Pro Tips

- Backups are created automatically before deletion
- All user actions are logged to Firebase
- Encryption is automatic for all data
- Admin panel accessible only to ADMIN_USER_ID
- Check logs in `/data/activity.log`

## 🔗 Useful Links

- Admin Dashboard: `/admin`
- Users: `/admin/users`
- Groups: `/admin/groups`
- Backups: `/admin/backups`
- Activity: `/admin/activity-logs`
- API Stats: `/api/admin/stats`
- API Users: `/api/admin/users`
- API Groups: `/api/admin/groups`

---

For more details, see documentation in the project root.
