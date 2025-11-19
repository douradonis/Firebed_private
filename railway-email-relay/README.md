# Railway Email Relay Service

Ένα απλό HTTP-to-SMTP proxy service που επιτρέπει την αποστολή email μέσω HTTP requests. Ιδανικό για platforms όπως το Render free tier που μπλοκάρουν SMTP outbound connections.

## 🎯 Σκοπός

Το Firebed_private Python app τρέχει στο Render (free tier) που δεν επιτρέπει SMTP connections. Αυτό το service:
- Τρέχει στο Railway (ή άλλο platform με SMTP access)
- Δέχεται HTTP POST requests με email data
- Στέλνει τα emails μέσω SMTP
- Υποστηρίζει όλα τα email providers (Gmail, Outlook, custom SMTP)

## 🚀 Deployment στο Railway

### 1. Προετοιμασία

Κάνε fork ή clone το repository και πήγαινε στο directory:

```bash
cd railway-email-relay
```

### 2. Deploy με Railway CLI

```bash
# Install Railway CLI (αν δεν το έχεις)
npm install -g @railway/cli

# Login στο Railway
railway login

# Initialize project
railway init

# Deploy
railway up
```

### 3. Deploy με Railway Web UI

1. Πήγαινε στο [railway.app](https://railway.app)
2. Κάνε click στο "New Project"
3. Επίλεξε "Deploy from GitHub repo"
4. Διάλεξε το repository σου
5. Όρισε το root directory ως `railway-email-relay`
6. Κάνε deploy

### 4. Πάρε το Public URL

Μετά το deployment, το Railway θα σου δώσει ένα public URL όπως:
```
https://your-app-name.railway.app
```

Αυτό το URL θα το χρησιμοποιήσεις στο Firebed_private configuration.

## 📝 Configuration στο Firebed_private

Στο Firebed_private admin panel:

1. Πήγαινε στο **Admin Settings** (`/admin/settings`)
2. Επίλεξε **Email Provider**: `Railway Proxy`
3. Βάλε το **Railway Proxy URL**: `https://your-app-name.railway.app`
4. Save settings

## 🧪 Testing

### Test το service απευθείας:

```bash
curl https://your-app-name.railway.app/health
```

Θα πρέπει να επιστρέψει:
```json
{
  "status": "ok",
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

### Test αποστολή email:

```bash
curl -X POST https://your-app-name.railway.app/send-mail \
  -H "Content-Type: application/json" \
  -d '{
    "smtp": {
      "host": "smtp.gmail.com",
      "port": 587,
      "secure": false,
      "user": "your-email@gmail.com",
      "pass": "your-app-password"
    },
    "mail": {
      "from": "your-email@gmail.com",
      "to": "recipient@example.com",
      "subject": "Test από Railway Relay",
      "text": "Αυτό είναι ένα test email!",
      "html": "<h1>Test Email</h1><p>Αυτό είναι ένα test email!</p>"
    }
  }'
```

## 🔒 Ασφάλεια

**ΣΗΜΑΝΤΙΚΟ:** Αυτή τη στιγμή το service δεν έχει authentication. Για production χρήση:

### Προσθήκη API Key Authentication (προτεινόμενο)

Τροποποίησε το `server.js`:

```javascript
// Στην αρχή του αρχείου
const API_KEY = process.env.API_KEY || 'your-secret-key';

// Middleware για authentication
app.use('/send-mail', (req, res, next) => {
    const authHeader = req.headers['authorization'];
    if (!authHeader || authHeader !== `Bearer ${API_KEY}`) {
        return res.status(401).json({ success: false, error: 'Unauthorized' });
    }
    next();
});
```

Στο Railway, όρισε environment variable:
```
API_KEY=your-super-secret-key-here
```

Στο Firebed_private, θα χρειαστεί να περάσεις το API key στα requests.

### Προσθήκη Rate Limiting (Προτεινόμενο για Production)

Για να προστατέψεις το service από abuse, πρόσθεσε rate limiting:

```bash
npm install express-rate-limit
```

Edit το `server.js`:

```javascript
const rateLimit = require('express-rate-limit');

// Add after other middleware
const limiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: 100, // Limit each IP to 100 requests per windowMs
    message: {
        success: false,
        error: 'Too many requests, please try again later.'
    }
});

// Apply to /send-mail route
app.post('/send-mail', limiter, async (req, res) => {
    // ... existing code
});
```

**Προτεινόμενα όρια:**
- Development: 100 requests / 15 minutes
- Production: 50 requests / 15 minutes (ή λιγότερο)
- Per IP tracking για να αποτρέψεις spam

## 📋 API Reference

### GET /

Service information και available endpoints.

**Response:**
```json
{
  "service": "Railway Email Relay",
  "status": "running",
  "version": "1.0.0",
  "endpoints": {
    "health": "GET /",
    "sendMail": "POST /send-mail"
  }
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

### POST /send-mail

Αποστολή email.

**Request Body:**
```json
{
  "smtp": {
    "host": "smtp.gmail.com",
    "port": 587,
    "secure": false,
    "user": "your_email@gmail.com",
    "pass": "your_app_password"
  },
  "mail": {
    "from": "sender@example.com",
    "to": "recipient@example.com",
    "subject": "Email Subject",
    "text": "Plain text body",
    "html": "<h1>HTML body</h1>",
    "attachments": []
  }
}
```

**Success Response:**
```json
{
  "success": true,
  "messageId": "<unique-message-id>",
  "accepted": ["recipient@example.com"],
  "rejected": [],
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Error message",
  "details": "Detailed error information"
}
```

## 🔧 SMTP Providers

### Gmail

```json
{
  "host": "smtp.gmail.com",
  "port": 587,
  "secure": false,
  "user": "your-email@gmail.com",
  "pass": "your-app-password"
}
```

**Σημείωση:** Χρειάζεσαι [App Password](https://support.google.com/accounts/answer/185833) από το Google Account settings.

### Outlook/Hotmail

```json
{
  "host": "smtp-mail.outlook.com",
  "port": 587,
  "secure": false,
  "user": "your-email@outlook.com",
  "pass": "your-password"
}
```

### Office 365

```json
{
  "host": "smtp.office365.com",
  "port": 587,
  "secure": false,
  "user": "your-email@yourdomain.com",
  "pass": "your-password"
}
```

### Custom SMTP Server

```json
{
  "host": "smtp.yourdomain.com",
  "port": 587,
  "secure": false,
  "user": "your-username",
  "pass": "your-password"
}
```

## 📦 Dependencies

- **express**: Web framework
- **nodemailer**: Email sending library
- **cors**: Cross-origin resource sharing

## 🐛 Troubleshooting

### "SMTP verification failed"

- Έλεγξε τα SMTP credentials
- Βεβαιώσου ότι έχεις enable "Less secure app access" ή App Passwords
- Έλεγξε ότι ο SMTP server είναι σωστός

### "Connection timeout"

- Βεβαιώσου ότι το Railway platform επιτρέπει outbound SMTP
- Έλεγξε το port (587 για STARTTLS, 465 για SSL)

### "Rate limit exceeded"

- Κάποιοι email providers έχουν rate limits
- Χρησιμοποίησε dedicated email service (Mailgun, SendGrid) για bulk emails

## 📄 License

MIT

## 🤝 Support

Για issues και questions, άνοιξε ένα issue στο GitHub repository.
