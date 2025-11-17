# Admin Dashboard Unification Guide

## Overview
Δημιουργήσαμε ένα **unified admin dashboard** (`dashboard_unified.html`) που συγχωνεύει όλες τις λειτουργίες από τα ξεχωριστά templates:

- `users.html` - Διαχείριση χρηστών ✅
- `groups.html` - Διαχείριση ομάδων ✅
- `activity_logs.html` - Δραστηριότητα συστήματος ✅
- `backups.html` - Backup & Restore ✅
- `send_email.html` - Αποστολή email ✅
- `settings.html` - Ρυθμίσεις συστήματος ✅

## Architecture

### Τabs Navigation
Το dashboard χρησιμοποιεί ένα tab-based interface με τις ακόλουθες ενότητες:

1. **📊 Επισκόπηση** - System Overview
   - Στατιστικά χρηστών & ομάδων
   - Πρόσφατη δραστηριότητα
   - System status

2. **👥 Χρήστες** - User Management
   - Λίστα χρηστών με φίλτρα
   - Προβολή λεπτομερειών
   - Διαγραφή χρηστών
   - Σχέση με ομάδες

3. **📁 Ομάδες** - Group Management
   - Δημιουργία νέων ομάδων
   - Λίστα ομάδων
   - Προβολή λεπτομερειών
   - Διαγραφή ομάδων

4. **📋 Δραστηριότητα** - Activity Logs
   - Φίλτρο ανά ομάδα
   - Φίλτρο ανά ενέργεια
   - Χρονοσειρά γεγονότων

5. **💾 Backups** - Backup & Restore
   - Backup όλων των δεδομένων
   - Backup συγκεκριμένης ομάδας
   - Λίστα διαθέσιμων backups
   - Restore λειτουργικότητα

6. **📧 Email** - User Communications
   - Επιλογή χρηστών
   - Σύνθεση μηνύματος
   - Αποστολή email

7. **⚙️ Ρυθμίσεις** - System Settings
   - Παράμετροι συστήματος
   - Επικίνδυνες ενέργειες

## API Endpoints

Το unified dashboard χρησιμοποιεί τα ακόλουθα API endpoints (όλα μέσω `admin_api` blueprint):

### Users
```
GET  /admin/api/users                  - Λίστα όλων των χρηστών
GET  /admin/api/users/<int:user_id>   - Λεπτομέρειες χρήστη
DELETE /admin/api/users/<int:user_id> - Διαγραφή χρήστη
POST /admin/api/users                  - Δημιουργία χρήστη
PUT  /admin/api/users/<int:user_id>   - Ενημέρωση χρήστη
```

### Groups
```
GET  /admin/api/groups                 - Λίστα όλων των ομάδων
GET  /admin/api/groups/<int:group_id>  - Λεπτομέρειες ομάδας
DELETE /admin/api/groups/<int:group_id> - Διαγραφή ομάδας
POST /admin/api/groups/<int:group_id>/members - Διαχείριση μελών
```

### Activity & Logs
```
GET  /admin/api/activity-logs          - Logs με φίλτρα
GET  /admin/api/activity               - Δραστηριότητα (legacy)
POST /admin/api/activity/clear         - Διαγραφή logs
```

### Backups
```
GET  /admin/api/backups                - Λίστα local backups
POST /admin/api/backup/all             - Backup όλα τα δεδομένα
POST /admin/api/backup/group/<group_name> - Backup ομάδας
POST /admin/api/backup/restore         - Restore από backup
GET  /admin/api/backup/list            - Remote backups (Firebase)
DELETE /admin/api/backup               - Διαγραφή remote backup
```

### Email
```
POST /admin/send-email                 - Αποστολή email σε χρήστες
```

## Frontend Components

### Modal Dialogs
- **User Detail Modal** - Προβολή λεπτομερειών χρήστη
- **Group Detail Modal** - Προβολή λεπτομερειών ομάδας

### JavaScript Functions

#### Tab Management
- `showTab(tabName)` - Εμφάνιση tab

#### Overview
- `loadStats()` - Φόρτωση στατιστικών
- `loadRecentActivity()` - Πρόσφατη δραστηριότητα

#### Users
- `loadUsers()` - Φόρτωση χρηστών
- `viewUserDetails(userId)` - Προβολή λεπτομερειών
- `deleteUser(userId, username)` - Διαγραφή χρήστη

#### Groups
- `loadGroups()` - Φόρτωση ομάδων
- `viewGroupDetails(groupId)` - Προβολή λεπτομερειών
- `deleteGroup(groupId, groupName)` - Διαγραφή ομάδας

#### Activity
- `loadActivity()` - Φόρτωση δραστηριότητας με φίλτρα

#### Backups
- `loadBackups()` - Φόρτωση διαθέσιμων backups
- `backupAllData()` - Backup όλων
- `backupSpecificGroup()` - Backup ομάδας
- `restoreBackup(backupName)` - Restore

#### Email
- `loadEmailUsers()` - Φόρτωση χρηστών για email
- `toggleAllEmailUsers()` - Select/Deselect όλους

## Backend Integration

### admin_panel.py
Παρέχει τις βασικές λειτουργίες:
- `admin_list_all_users()` - Λίστα χρηστών
- `admin_get_user_details()` - Λεπτομέρειες χρήστη
- `admin_list_all_groups()` - Λίστα ομάδων
- `admin_get_group_details()` - Λεπτομέρειες ομάδας
- `admin_get_activity_logs()` - Δραστηριότητα
- `admin_list_backups()` - Backups
- `admin_backup_group()` - Backup ομάδας
- `admin_restore_backup()` - Restore

### admin_api.py
Endpoints blueprint που παρέχει REST API:
- Όλα τα CRUD operations
- Filtering & searching
- Backup/Restore operations

### app.py
Main route:
- `@app.route("/admin")` - Εμφανίζει το `dashboard_unified.html`

## Features

✅ **Tab-based Navigation** - Εύκολη πλοήγηση μεταξύ ενοτήτων
✅ **Real-time Stats** - Ζωντανή ενημέρωση στατιστικών
✅ **Modal Details** - Λεπτομέρειες χωρίς page reload
✅ **Inline Actions** - Quick actions (delete, view, etc)
✅ **Filtering** - Advanced filters για activity & logs
✅ **Email Integration** - Αποστολή μηνυμάτων σε χρήστες
✅ **Backup/Restore** - Complete backup management
✅ **Greek UI** - Πλήρης ελληνική διεπαφή
✅ **Responsive Design** - Mobile-friendly layout
✅ **Error Handling** - Graceful error messages

## Styling

Χρησιμοποιείται Tailwind CSS για το styling:
- `bg-*` classes για backgrounds
- `text-*` classes για κείμενο
- `border-*` classes για borders
- `p-*` classes για padding
- `m-*` classes για margins
- `flex`, `grid` για layouts
- `hover:*` για interactions

## Future Improvements

- [ ] Real-time updates με WebSockets
- [ ] Advanced search & filtering
- [ ] Export σε CSV/JSON
- [ ] Two-factor authentication
- [ ] Activity graph visualizations
- [ ] Bulk operations
- [ ] Custom admin roles

## Troubleshooting

### Endpoints not working?
1. Check `admin_api.py` blueprint is registered in `app.py`
2. Verify `ADMIN_USER_ID` environment variable
3. Check user has admin privileges (`is_admin` flag)

### Modal not appearing?
1. Check browser console for JS errors
2. Verify modal HTML exists in template
3. Check CSS classes for display/hidden

### API calls failing?
1. Check server logs for errors
2. Verify authentication (login required)
3. Check JSON response format
4. Look for CORS issues

## Testing

Για δοκιμή του dashboard:

```bash
# Start application
python app.py

# Login as admin
# Navigate to http://localhost:5000/admin

# Try each tab:
# - Users tab
# - Groups tab
# - Activity tab
# - Backups tab
# - Email tab
# - Settings tab
```

## Files Modified

- ✅ Created: `/templates/admin/dashboard_unified.html` - Main dashboard
- ✅ Updated: `/app.py` - Changed route to use new dashboard
- ✅ Updated: `/admin_api.py` - Added missing endpoints

## Files Still Available

Τα παλιά templates εξακολουθούν να υπάρχουν και μπορούν να χρησιμοποιηθούν αν χρειαστεί:
- `users.html`
- `groups.html`
- `activity_logs.html`
- `backups.html`
- `send_email.html`
- `settings.html`
- `dashboard.html`
- `dashboard_new.html`
