# Firebase Integration with Custom Frontend

## Overview

Firebed Private τώρα χρησιμοποιεί **Firebase** για όλες τις λειτουργίες authentication και διαχείρισης δεδομένων πελατών, με το δικό σας **custom frontend**.

## 📋 What Changed

### 1. Authentication Routes (Firebase)
- ✅ Login: `/firebase-auth/login` → Firebase credentials
- ✅ Signup: `/firebase-auth/signup` → Firebase + local DB
- ✅ Profile: `/firebase-auth/profile` → User management
- ✅ Password Reset: `/firebase-auth/password/reset`

### 2. Frontend Integration
Χρησιμοποιούμε τις **υπάρχουσες σελίδες** σας με τροποποιήσεις:

```
templates/auth/login.html      → Firebase Email/Password
templates/auth/signup.html     → Firebase Registration
templates/auth/profile.html    → Profile Management
templates/auth/account.html    → Account Settings
```

### 3. Database (Firebase Realtime)
Όλα τα δεδομένα πελατών αποθηκεύονται στο **Firebase Realtime Database**:

```
/users/{uid}
  ├── email
  ├── display_name
  ├── groups: [list]
  ├── created_at
  └── active

/groups/{group_name}
  ├── members: [list of UIDs]
  ├── created_at
  └── metadata

/activity_logs/{group_name}/{timestamp}
  ├── user_id
  ├── action
  ├── timestamp
  └── details
```

### 4. Admin Dashboard
**Νέα εντελώς ανανεωμένη σελίδα admin** με:
- 📊 Real-time statistics
- 👥 User management
- 📁 Group management
- 📋 Activity logs
- 💾 Backup/Restore
- ⚙️ System settings

**URL**: `/admin` (ίδια όπως πριν, αλλά καινούρια διεπαφή)

## 🔗 API Endpoints

### Admin API (JSON)
Όλα τα δεδομένα είναι διαθέσιμα μέσω REST API:

```
GET    /admin/api/users                  # List all users
GET    /admin/api/users/<uid>            # Get user details
DELETE /admin/api/users/<uid>            # Delete user

GET    /admin/api/groups                 # List all groups
GET    /admin/api/groups/<name>          # Get group details
DELETE /admin/api/groups/<name>          # Delete group

GET    /admin/api/activity               # Activity logs
GET    /admin/api/stats                  # System statistics

POST   /admin/api/backup/all             # Full system backup
POST   /admin/api/backup/group/<name>    # Group backup
POST   /admin/api/activity/clear         # Clear logs (dangerous!)
```

## 🔐 Authentication Flow

### User Registration
```
1. User visits /firebase-auth/signup
2. Fills: email, password, display_name
3. POST to Firebase Auth
4. User profile created in /users/{uid}
5. Local User record created for Flask-Login
6. Redirect to login
```

### User Login
```
1. User visits /firebase-auth/login
2. Fills: email, password
3. Firebase verifies credentials
4. Flask-Login session established
5. User can access groups
```

### Group Management
```
1. User joins group → added to /users/{uid}/groups
2. User is listed in /groups/{group_name}/members
3. Activity logged to /activity_logs/{group_name}/{timestamp}
```

## 📁 File Structure

### New Files
```
firebase_auth_handlers.py      # Firebase auth logic (430 lines)
firebase_auth_routes.py        # Auth endpoints (280 lines)
admin_api.py                   # Admin REST API (400 lines)
templates/admin/dashboard_new.html  # New admin UI
templates/firebase_auth/       # Auth templates (updated)
  ├── signup.html
  ├── login.html
  ├── profile.html
  └── password_reset.html
```

### Modified Files
```
app.py                         # Added Firebase blueprints
templates/auth/login.html      # Updated to Firebase
templates/auth/signup.html     # Updated to Firebase
firebase_config.py             # Fixed read_data() bug
```

## 🧪 Testing

### Test User Registration
```bash
curl -X POST http://localhost:5000/firebase-auth/signup \
  -d "email=test@example.com&password=Test123456&display_name=Test"
```

### Test Admin API
```bash
# Get all users (must be logged in as admin)
curl -X GET http://localhost:5000/admin/api/users \
  -H "Cookie: session=YOUR_SESSION"

# Get system stats
curl -X GET http://localhost:5000/admin/api/stats \
  -H "Cookie: session=YOUR_SESSION"
```

## 🎯 Frontend Integration Steps

### 1. Update Login Form
Your existing `templates/auth/login.html` now posts to:
```html
<form method="post" action="{{ url_for('firebase_auth.firebase_login') }}">
  <input type="email" name="email" required />
  <input type="password" name="password" required />
  <button type="submit">Login</button>
</form>
```

### 2. Access User Data in Templates
```html
{% if current_user.is_authenticated %}
  User: {{ current_user.email }}
  Display Name: {{ current_user.username }}
  Groups: {{ user_groups }}
{% endif %}
```

### 3. Use Admin API
```javascript
// Fetch users
fetch('/admin/api/users', {
  method: 'GET',
  headers: {'Content-Type': 'application/json'}
})
.then(r => r.json())
.then(data => {
  console.log('Users:', data.users);
});

// Get statistics
fetch('/admin/api/stats')
  .then(r => r.json())
  .then(data => {
    console.log('Total users:', data.stats.total_users);
    console.log('Total groups:', data.stats.total_groups);
  });
```

## 🔧 Configuration

### Environment Variables (.env)
```
FIREBASE_CREDENTIALS_PATH=./firebase-key.json
FIREBASE_DATABASE_URL=https://your-project.firebaseio.com
FIREBASE_PROJECT_ID=your-project-id
ADMIN_USER_ID=1
```

### Flask Configuration
```python
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "1")
```

## 📊 Data Flow

```
┌─────────────────────────────────────────────────────┐
│           User Registration                         │
├─────────────────────────────────────────────────────┤
│ Frontend (form) → Firebase Auth → Firebase DB       │
│                                ↓                    │
│                           Local DB (Flask-Login)    │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│           Admin Operations                          │
├─────────────────────────────────────────────────────┤
│ Admin Panel → Admin API → Firebase DB               │
│           ↓                                         │
│     Activity Logs (audit trail)                     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│           Group Management                          │
├─────────────────────────────────────────────────────┤
│ Users join groups → /users/{uid}/groups             │
│                 → /groups/{group}/members           │
│                 → Activity logged                   │
└─────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Access Login
```
http://localhost:5000/firebase-auth/login
```

### 2. Create Account
```
http://localhost:5000/firebase-auth/signup
```

### 3. View Admin Panel
```
http://localhost:5000/admin
```

### 4. Use API
```bash
# Get all users
curl http://localhost:5000/admin/api/users

# Get activity logs
curl http://localhost:5000/admin/api/activity

# Get system stats
curl http://localhost:5000/admin/api/stats
```

## 🔍 Debugging

### Check Firebase Connection
```bash
python << 'EOF'
import firebase_config
firebase_config.init_firebase()
print(f"Firebase enabled: {firebase_config.is_firebase_enabled()}")
EOF
```

### View Logs
```bash
tail -f firebed.log | grep Firebase
tail -f firebed.log | grep admin
```

### Check Firebase Data
```bash
python << 'EOF'
import firebase_config
firebase_config.init_firebase()

# List all users
users = firebase_config.firebase_read_data('/users')
print(f"Users: {users}")

# List all groups
groups = firebase_config.firebase_read_data('/groups')
print(f"Groups: {groups}")
EOF
```

## 🛡️ Security

### Admin Access
- Only user with `ADMIN_USER_ID` can access `/admin`
- All admin API calls require authentication
- Admin-only decorator: `@_require_admin`

### Password Security
- Passwords managed by Firebase (secure hashing)
- Passwords never logged
- Custom tokens for client-side SDK

### Activity Logging
- All admin actions logged
- Timestamps recorded
- User identification included

## 📚 API Response Examples

### Get Users
```json
{
  "success": true,
  "users": [
    {
      "uid": "user123",
      "email": "user@example.com",
      "display_name": "User Name",
      "groups": ["group1", "group2"],
      "created_at": "2025-11-14T10:30:00Z"
    }
  ],
  "count": 1
}
```

### Get Stats
```json
{
  "success": true,
  "stats": {
    "total_users": 5,
    "total_groups": 3,
    "recent_activity_24h": 42,
    "firebase_enabled": true,
    "timestamp": "2025-11-14T11:30:00Z"
  }
}
```

### Get Activity Logs
```json
{
  "success": true,
  "logs": [
    {
      "timestamp": "2025-11-14T11:20:00Z",
      "user_id": "user123",
      "group": "group1",
      "action": "user_logged_in",
      "details": { "ip": "192.168.1.1" }
    }
  ],
  "count": 1
}
```

## ⚠️ Important Notes

1. **Firebase Realtime Database** - All user/group data is there
2. **Local SQLite DB** - Only Flask-Login sessions
3. **Encryption** - Data can be encrypted at rest (per-group keys)
4. **Activity Trail** - All operations logged for audit
5. **Backups** - Full system backup available via admin

## 🔄 Migration from Old Auth

If you had old user accounts:
1. Users need to create new Firebase accounts
2. Old data can be migrated using backups
3. Groups can be recreated in Firebase

## 📞 Support

- Check `firebed.log` for errors
- Review Firebase Console for auth events
- Test endpoints with `/admin/api/...`
- Verify environment variables in `.env`

---

**System is now fully Firebase-backed with custom frontend!** 🎉
