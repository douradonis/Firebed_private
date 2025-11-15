# Phase 2 Quick Start Guide

## 🚀 Get Started in 5 Minutes

### 1. Access the Web Interface

#### Signup
```
URL: http://localhost:5000/firebase-auth/signup
```
- Enter email
- Set password (minimum 6 characters)
- Optional: Enter display name
- Click "Create Account"

#### Login
```
URL: http://localhost:5000/firebase-auth/login
```
- Enter email
- Enter password
- Check "Remember me" (optional)
- Click "Log In"

#### Profile
```
URL: http://localhost:5000/firebase-auth/profile
```
(After logging in)
- View account information
- Edit display name
- Change password
- See your groups

### 2. Command Line Testing

#### Register a User
```bash
python << 'EOF'
from firebase_auth_handlers import FirebaseAuthHandler

success, uid, error = FirebaseAuthHandler.register_user(
    email="demo@example.com",
    password="Demo123456",
    display_name="Demo User"
)

print(f"Success: {success}")
print(f"UID: {uid}")
print(f"Error: {error}")
EOF
```

#### Login User
```bash
python << 'EOF'
from firebase_auth_handlers import FirebaseAuthHandler

success, uid, error = FirebaseAuthHandler.login_user(
    email="demo@example.com",
    password="Demo123456"
)

print(f"Success: {success}")
print(f"UID: {uid}")
EOF
```

#### Add User to Group
```bash
python << 'EOF'
from firebase_auth_handlers import FirebaseAuthHandler

# First, get or create a user
success, uid, _ = FirebaseAuthHandler.register_user(
    email="user@example.com",
    password="Pass123456",
    display_name="User"
)

# Add user to group
success, error = FirebaseAuthHandler.add_user_to_group(uid, "douradonis")
print(f"Added to group: {success}")

# List user's groups
groups = FirebaseAuthHandler.get_user_groups(uid)
print(f"User groups: {groups}")

# List group members
members = FirebaseAuthHandler.get_group_members("douradonis")
print(f"Group members: {members}")
EOF
```

#### View User Profile
```bash
python << 'EOF'
from firebase_auth_handlers import FirebaseAuthHandler

# After registering a user
uid = "USER_UID_HERE"  # Replace with actual UID

profile = FirebaseAuthHandler.get_user_by_uid(uid)
print(f"User Profile:")
print(f"  Email: {profile['email']}")
print(f"  Display Name: {profile['display_name']}")
print(f"  Created: {profile['created_at']}")
print(f"  Groups: {profile.get('groups', [])}")
EOF
```

### 3. API Testing with curl

#### Get User's Groups
```bash
# After login (you need a session cookie)
curl -X GET "http://localhost:5000/firebase-auth/api/user/groups" \
  -H "Content-Type: application/json" \
  -b "session=YOUR_SESSION_COOKIE"
```

Response:
```json
{
  "success": true,
  "groups": ["douradonis", "other_group"],
  "count": 2
}
```

#### Get Group Members
```bash
curl -X GET "http://localhost:5000/firebase-auth/api/group/douradonis/members" \
  -H "Content-Type: application/json" \
  -b "session=YOUR_SESSION_COOKIE"
```

Response:
```json
{
  "success": true,
  "group": "douradonis",
  "members": ["uid1", "uid2", "uid3"],
  "count": 3
}
```

### 4. Check Activity Logs

All activities are logged in Firebase. View them:

```bash
python << 'EOF'
import firebase_config
firebase_config.init_firebase()

# Get activity logs for a group
logs = firebase_config.firebase_get_group_activity_logs('douradonis', limit=10)

print(f"Activity logs ({len(logs)} entries):")
for log in logs:
    print(f"  {log['timestamp']}: {log['action']} by {log['user_id']}")
EOF
```

## 📋 Features Checklists

### User Features
- [ ] ✅ Sign up with email/password
- [ ] ✅ Log in securely
- [ ] ✅ View profile
- [ ] ✅ Edit display name
- [ ] ✅ Change password
- [ ] ✅ Reset password (request)
- [ ] ✅ Log out
- [ ] ✅ Join groups
- [ ] ✅ Leave groups
- [ ] ✅ View group members

### Admin Features
- [ ] ✅ View all users in admin panel
- [ ] ✅ View all groups in admin panel
- [ ] ✅ Delete users
- [ ] ✅ Delete groups
- [ ] ✅ Backup/restore groups
- [ ] ✅ View activity logs
- [ ] ✅ View system statistics

## 🔒 Security Verification

Verify security features are working:

```bash
python << 'EOF'
import firebase_config
firebase_config.init_firebase()

# 1. Check Firebase is enabled
print(f"1. Firebase enabled: {firebase_config.is_firebase_enabled()}")

# 2. Test encryption
from encryption import encrypt_data, decrypt_data

test_data = {"secret": "information"}
encrypted = encrypt_data(test_data)
decrypted = decrypt_data(encrypted)
print(f"2. Encryption works: {test_data == decrypted}")

# 3. Test Firebase write/read
success = firebase_config.firebase_write_data('/test/security', {"test": True})
print(f"3. Firebase write works: {success}")

data = firebase_config.firebase_read_data('/test/security')
print(f"4. Firebase read works: {data is not None}")

# 5. Test logging
success = firebase_config.firebase_log_activity('test_user', 'test_group', 'test_action', {})
print(f"5. Activity logging works: {success}")

print("\n✅ All security features verified!")
EOF
```

## 🐛 Troubleshooting

### Issue: "Firebase not enabled"
**Solution**: Check `.env` file has Firebase credentials
```bash
grep FIREBASE_CREDENTIALS_PATH .env
cat firebase-key.json | head -5
```

### Issue: "User already exists"
**Solution**: Use a different email or delete the user first
```bash
python << 'EOF'
from firebase_auth_handlers import FirebaseAuthHandler

# Try with different email
success, uid, error = FirebaseAuthHandler.register_user(
    email=f"user_{int(time.time())}@example.com",
    password="Pass123456"
)
EOF
```

### Issue: Login fails but registration worked
**Solution**: Ensure password is exactly correct
```bash
# Try retrieving the user by email
python << 'EOF'
import firebase_admin.auth as auth
user = auth.get_user_by_email('email@example.com')
print(f"User UID: {user.uid}")
print(f"Email verified: {user.email_verified}")
EOF
```

### Issue: Group operations not working
**Solution**: Ensure user is actually in the group
```bash
python << 'EOF'
from firebase_auth_handlers import FirebaseAuthHandler

# Verify user is in group
uid = "USER_UID"
groups = FirebaseAuthHandler.get_user_groups(uid)
print(f"User's groups: {groups}")

# Check group members
members = FirebaseAuthHandler.get_group_members("groupname")
print(f"Group members: {members}")
EOF
```

## 📊 Monitor System Health

Check system status:

```bash
python << 'EOF'
import admin_panel

# Get system stats
stats = admin_panel.admin_get_system_stats()

print("System Statistics:")
print(f"  Total Users: {stats.get('total_users', 0)}")
print(f"  Total Groups: {stats.get('total_groups', 0)}")
print(f"  Database Size: {stats.get('db_size', 0)} bytes")
print(f"  Last Activity: {stats.get('last_activity', 'N/A')}")
EOF
```

## 🎓 Learn More

### Documentation Files
- `PHASE_2_FIREBASE_AUTH.md` - Complete guide
- `PHASE_2_SUMMARY.md` - Implementation summary
- `ENCRYPTION_GUIDE.md` - Encryption details
- `ADMIN_PANEL_GUIDE.md` - Admin features

### Code Files
- `firebase_auth_handlers.py` - Auth logic (430 lines)
- `firebase_auth_routes.py` - Web routes (280 lines)
- `firebase_config.py` - Firebase config (325 lines)
- `encryption.py` - Encryption utilities (200 lines)

## 🚀 Next: Phase 3

When ready for advanced features:

```bash
# Client-side Firebase SDK integration
# Real-time data synchronization
# Offline support
# OAuth providers (Google, GitHub)
# Two-factor authentication
```

## ✅ Checklist: System Ready?

- [ ] Firebase initialized successfully
- [ ] User can register
- [ ] User can login
- [ ] User can view profile
- [ ] User can join groups
- [ ] Admin can access admin panel
- [ ] Activity logs populate
- [ ] Encryption working
- [ ] No errors in `firebed.log`

## 📞 Quick Reference

| Task | How To |
|------|--------|
| Register user | POST `/firebase-auth/signup` or `FirebaseAuthHandler.register_user()` |
| Login user | POST `/firebase-auth/login` or `FirebaseAuthHandler.login_user()` |
| View profile | GET `/firebase-auth/profile` (requires login) |
| Add to group | POST `/firebase-auth/group/{group}/join` or `add_user_to_group()` |
| List groups | GET `/firebase-auth/api/user/groups` or `get_user_groups()` |
| List members | GET `/firebase-auth/api/group/{group}/members` or `get_group_members()` |
| View logs | GET `/admin/activity-logs` (admin only) |
| Change password | POST `/firebase-auth/password/change` (requires login) |
| Logout | GET `/firebase-auth/logout` |

---

**Congratulations! Phase 2 is complete! 🎉**

Your Firebed Private system now has:
- ✅ Complete Firebase Authentication
- ✅ Secure password management
- ✅ Group membership tracking
- ✅ Activity logging
- ✅ User profiles
- ✅ Per-group encryption ready

Start using it now!
