#!/bin/bash
# Quick Start Guide - Email Verification & Password Reset System

echo "🚀 Firebed Email System - Quick Start"
echo "======================================"
echo ""

# Step 1: Initialize Database
echo "Step 1: Initialize Database"
echo "$ python3 scripts/reset_db.py"
python3 scripts/reset_db.py
echo ""

# Step 2: Create Test Users
echo "Step 2: Create Test Users"
echo "$ python3 scripts/create_test_users.py"
python3 scripts/create_test_users.py
echo ""

# Step 3: Run Health Check
echo "Step 3: System Health Check"
echo "$ python3 test_email_system.py"
python3 test_email_system.py
echo ""

echo "✅ Setup complete!"
echo ""
echo "To start the application:"
echo "$ python3 app.py"
echo ""
echo "Test credentials:"
echo "  Admin: admin / admin123"
echo "  User:  testuser1 / test123"
echo ""
echo "To enable email sending, set SMTP environment variables:"
echo "  export SMTP_SERVER=smtp.gmail.com"
echo "  export SMTP_PORT=587"
echo "  export SMTP_USER=your-email@gmail.com"
echo "  export SMTP_PASSWORD=your-app-password"
echo "  export SENDER_EMAIL=your-email@gmail.com"
echo "  export APP_URL=http://localhost:5000"
