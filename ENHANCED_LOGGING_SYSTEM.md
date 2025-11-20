# Enhanced User Activity Logging System

## Περιγραφή

Το σύστημα καταγράφει αναλυτικά όλες τις ενέργειες των χρηστών με πλήρη metadata για έλεγχο από τον admin.

## Τι Καταγράφεται

### 1. Login/Logout Events
- **Login**: Καταγράφει σύνδεση χρήστη
  - Email χρήστη
  - Username
  - IP address
  - Αν είναι admin
  - Πλήθος ομάδων χρήστη
  
- **Logout**: Καταγράφει αποσύνδεση χρήστη
  - Email χρήστη
  - Username
  - Διάρκεια σύνδεσης σε λεπτά
  - IP address

### 2. Backup Operations
- **Backup Download**: Λήψη αντιγράφου ασφαλείας
  - Όνομα αρχείου
  - Μέγεθος αρχείου (MB)
  - Τύπος backup (group/customer)
  - Λίστα πελατών (αν επιλέχθηκαν συγκεκριμένοι)
  - Πλήθος πελατών
  
- **Backup Upload**: Φόρτωση αντιγράφου ασφαλείας
  - Όνομα αρχείου
  - Μέγεθος αρχείου (MB)
  - Πλήθος αρχείων στο backup
  - Αν περιέχει credentials

### 3. Delete Operations
- **Delete Rows**: Διαγραφή γραμμών από πίνακα
  - Λίστα MARKs που διαγράφηκαν
  - Συνολικός αριθμός γραμμών
  - Πλήθος διαγραφών από Excel
  - Πλήθος διαγραφών από Epsilon cache
  - Όνομα αρχείου Excel

### 4. Export Operations
- **Export Bridge**: Λήψη γέφυρας (Κινήσεις)
  - Κατηγορία βιβλίων (Β ή Γ)
  - Αριθμός γραμμών
  - Μέγεθος αρχείου (MB)
  - Όνομα αρχείου
  - Αν περιλαμβάνει b_kat.ect
  - ΑΦΜ πελάτη

- **Export Expenses**: Λήψη εξοδολογίου
  - Κατηγορία βιβλίων (Β ή Γ)
  - Αριθμός γραμμών
  - Μέγεθος αρχείου (MB)
  - Όνομα αρχείου
  - ΑΦΜ πελάτη

### 5. Fetch Operations
- **Fetch Data**: Ανάκτηση δεδομένων MyDATA
  - Ημερομηνία από
  - Ημερομηνία έως
  - Πλήθος εγγραφών που ανακτήθηκαν

## Τεχνική Υλοποίηση

### Κεντρική Συνάρτηση: `log_user_activity()`

Βρίσκεται στο αρχείο `utils.py` και καλείται από όλα τα σημεία του κώδικα που χρειάζονται logging.

```python
from utils import log_user_activity

log_user_activity(
    user_id=current_user.id,
    group_name='group_vat',
    action='login',
    details={
        'email': 'user@example.com',
        'ip_address': '192.168.1.1'
    },
    user_email='user@example.com',
    user_username='username'
)
```

### Παράμετροι

- `user_id`: Identifier χρήστη (Firebase UID, database ID, ή username)
- `group_name`: Όνομα ομάδας/πελάτη (ΑΦΜ ή group identifier)
- `action`: Τύπος ενέργειας (π.χ. 'login', 'backup_download', κλπ)
- `details`: Dictionary με επιπλέον λεπτομέρειες
- `user_email`: (Optional) Email χρήστη
- `user_username`: (Optional) Username χρήστη

### Τύποι Actions

| Action | Περιγραφή |
|--------|-----------|
| `login` | Σύνδεση χρήστη |
| `logout` | Αποσύνδεση χρήστη |
| `backup_download` | Λήψη αντιγράφου ασφαλείας |
| `backup_upload` | Φόρτωση αντιγράφου ασφαλείας |
| `delete_rows` | Διαγραφή γραμμών από πίνακα |
| `export_bridge` | Λήψη γέφυρας (Κινήσεις) |
| `export_expenses` | Λήψη εξοδολογίου |
| `fetch_data` | Ανάκτηση δεδομένων MyDATA |
| `search_mark` | Αναζήτηση MARK |
| `save_invoice` | Αποθήκευση παραστατικού |

## Προβολή Logs στο Admin Panel

### API Endpoint

```
GET /admin/api/activity-logs
```

### Query Parameters

- `group`: Φιλτράρισμα ανά ομάδα
- `action`: Φιλτράρισμα ανά τύπο ενέργειας
- `search`: Αναζήτηση σε όλα τα πεδία
- `limit`: Μέγιστος αριθμός αποτελεσμάτων (default: 100)

### Response Format

```json
{
  "success": true,
  "logs": [
    {
      "timestamp": "2025-11-20T10:30:00Z",
      "user_id": "user123",
      "user_email": "user@example.com",
      "user_username": "username",
      "group": "123456789",
      "action": "export_bridge",
      "summary": "Λήψη γέφυρας κατηγορίας Β (150 γραμμές, 2.5 MB)",
      "details": {
        "book_category": "Β",
        "rows_count": 150,
        "file_size_mb": 2.5,
        "file_name": "123456789_EPSILON_BRIDGE_KINHSEIS.xlsx",
        "includes_b_kat": true,
        "vat": "123456789"
      },
      "ip_address": "192.168.1.1"
    }
  ],
  "count": 1
}
```

### Enhanced Fields

Κάθε log entry περιέχει:
- **summary**: Αναγνώσιμη περίληψη της ενέργειας στα Ελληνικά
- **user_email**: Email του χρήστη
- **user_username**: Username του χρήστη
- **ip_address**: IP address από όπου έγινε η ενέργεια
- **details**: Αναλυτικές λεπτομέρειες σε JSON format

## Αποθήκευση Logs

Τα logs αποθηκεύονται:

1. **Firebase Realtime Database**: `/activity_logs/{group}/{timestamp}`
2. **Local JSON files**: `data/{group}/activity.log` (ένα JSON object ανά γραμμή)

Αυτή η διπλή αποθήκευση εξασφαλίζει:
- Κεντρική προβολή μέσω Firebase για το admin panel
- Τοπικό backup για offline ανάλυση και debugging

## Παράδειγμα Χρήσης στο Admin Panel

Ο admin μπορεί να δει:

### Όλες τις συνδέσεις χρήστη
```
GET /admin/api/activity-logs?action=login&limit=50
```

### Όλες τις λήψεις γέφυρας για συγκεκριμένο ΑΦΜ
```
GET /admin/api/activity-logs?group=123456789&action=export_bridge
```

### Όλες τις ενέργειες συγκεκριμένου χρήστη
```
GET /admin/api/activity-logs?search=user@example.com
```

### Όλες τις διαγραφές
```
GET /admin/api/activity-logs?action=delete_rows
```

## Συντήρηση

### Log Rotation

Για να αποφευχθεί η υπερβολική αύξηση των logs:

1. Τα Firebase logs μπορούν να διαγραφούν μαζικά μέσω Firebase Console
2. Τα local logs μπορούν να αρχειοθετούνται/διαγράφονται χειροκίνητα από το `data/{group}/activity.log`

### Προτεινόμενη Πολιτική

- Διατήρηση logs για 6-12 μήνες
- Αρχειοθέτηση παλαιότερων logs σε εξωτερικό storage
- Τακτικός έλεγχος μεγέθους log files

## Προστασία Προσωπικών Δεδομένων

Τα logs περιέχουν:
- Email addresses
- IP addresses
- User activities

**Σημαντικό**: Πρέπει να τηρούνται οι κανόνες GDPR για τη διαχείριση και αποθήκευση αυτών των δεδομένων.

## Troubleshooting

### Αν δεν εμφανίζονται logs

1. Ελέγξτε αν το Firebase είναι ενεργοποιημένο
2. Ελέγξτε το `data/{group}/activity.log` για τοπικά logs
3. Ελέγξτε τα server logs για σφάλματα στο logging

### Αν το logging είναι αργό

Η συνάρτηση `log_user_activity()` είναι σχεδιασμένη να αποτυγχάνει σιωπηλά (fail silently) για να μην επηρεάζει την κύρια λειτουργία της εφαρμογής.

## Future Enhancements

Πιθανές μελλοντικές βελτιώσεις:

1. Dashboard με γραφήματα για visualization των activities
2. Email alerts για συγκεκριμένες ενέργειες (π.χ. πολλαπλές διαγραφές)
3. Αυτόματη ανίχνευση ύποπτων δραστηριοτήτων
4. Export logs σε CSV/Excel για ανάλυση
5. Real-time monitoring dashboard
