/**
 * Railway Email Relay Service
 * 
 * This service acts as an HTTP-to-SMTP proxy, allowing applications
 * on platforms that block SMTP (like Render free tier) to send emails
 * via HTTP requests.
 * 
 * Deploy this on Railway or similar platform that allows SMTP outbound.
 */

const express = require('express');
const nodemailer = require('nodemailer');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json({ limit: '10mb' })); // Support larger payloads for attachments
app.use(cors()); // Allow cross-origin requests

// Health check endpoint
app.get('/', (req, res) => {
    res.json({
        service: 'Railway Email Relay',
        status: 'running',
        version: '1.0.0',
        endpoints: {
            health: 'GET /',
            sendMail: 'POST /send-mail'
        }
    });
});

// Health check endpoint (alternative)
app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

/**
 * Send email endpoint
 * 
 * POST /send-mail
 * 
 * Request body:
 * {
 *   "smtp": {
 *     "host": "smtp.gmail.com",
 *     "port": 587,
 *     "secure": false,  // true for 465, false for other ports
 *     "user": "your_email@gmail.com",
 *     "pass": "your_app_password"
 *   },
 *   "mail": {
 *     "from": "sender@example.com",
 *     "to": "recipient@example.com",
 *     "subject": "Test Email",
 *     "text": "Plain text body",
 *     "html": "<h1>HTML body</h1>",
 *     "attachments": [...]  // Optional
 *   }
 * }
 */
app.post('/send-mail', async (req, res) => {
    try {
        const { smtp, mail } = req.body;

        // Validate request
        if (!smtp || !mail) {
            return res.status(400).json({
                success: false,
                error: 'Missing required fields: smtp and mail'
            });
        }

        // Validate SMTP config
        if (!smtp.host || !smtp.user || !smtp.pass) {
            return res.status(400).json({
                success: false,
                error: 'SMTP configuration incomplete. Required: host, user, pass'
            });
        }

        // Validate mail config
        if (!mail.from || !mail.to || !mail.subject) {
            return res.status(400).json({
                success: false,
                error: 'Mail configuration incomplete. Required: from, to, subject'
            });
        }

        // Create transporter with provided SMTP settings
        const transporter = nodemailer.createTransport({
            host: smtp.host,
            port: smtp.port || 587,
            secure: smtp.secure || false, // true for 465, false for other ports
            auth: {
                user: smtp.user,
                pass: smtp.pass
            },
            // Additional options
            tls: {
                rejectUnauthorized: smtp.rejectUnauthorized !== false // Allow override
            }
        });

        // Verify transporter configuration
        try {
            await transporter.verify();
        } catch (verifyError) {
            console.error('SMTP verification failed:', verifyError);
            return res.status(500).json({
                success: false,
                error: 'SMTP server verification failed',
                details: verifyError.message
            });
        }

        // Prepare mail options
        const mailOptions = {
            from: mail.from,
            to: mail.to,
            subject: mail.subject,
            text: mail.text,
            html: mail.html,
            attachments: mail.attachments || []
        };

        // Optional fields
        if (mail.cc) mailOptions.cc = mail.cc;
        if (mail.bcc) mailOptions.bcc = mail.bcc;
        if (mail.replyTo) mailOptions.replyTo = mail.replyTo;

        // Send email
        const info = await transporter.sendMail(mailOptions);

        console.log('Email sent successfully:', {
            messageId: info.messageId,
            to: mail.to,
            subject: mail.subject,
            timestamp: new Date().toISOString()
        });

        res.json({
            success: true,
            messageId: info.messageId,
            accepted: info.accepted,
            rejected: info.rejected,
            timestamp: new Date().toISOString()
        });

    } catch (error) {
        console.error('Error sending email:', error);
        
        res.status(500).json({
            success: false,
            error: error.message || 'Failed to send email',
            type: error.name
        });
    }
});

// Error handling middleware
app.use((err, req, res, next) => {
    console.error('Unhandled error:', err);
    res.status(500).json({
        success: false,
        error: 'Internal server error',
        message: err.message
    });
});

// Start server
app.listen(PORT, () => {
    console.log(`🚀 Railway Email Relay running on port ${PORT}`);
    console.log(`📧 Ready to relay emails via HTTP → SMTP`);
    console.log(`🔗 Endpoints:`);
    console.log(`   GET  /         - Service info`);
    console.log(`   GET  /health   - Health check`);
    console.log(`   POST /send-mail - Send email`);
});
