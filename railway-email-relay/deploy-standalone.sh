#!/bin/bash
# Railway Email Relay - Standalone Deployment Script
# 
# Αυτό το script δημιουργεί ένα standalone directory που μπορείς να κάνεις deploy
# απευθείας στο Railway free tier (χωρίς να χρειάζεται custom root directory)

set -e

echo "🚀 Railway Email Relay - Standalone Deployment Setup"
echo "====================================================="
echo ""

# Check if we're in the railway-email-relay directory
if [ ! -f "server.js" ]; then
    echo "❌ Error: Πρέπει να τρέξεις αυτό το script από το railway-email-relay directory"
    echo "   Τρέξε: cd railway-email-relay && ./deploy-standalone.sh"
    exit 1
fi

# Create standalone directory
STANDALONE_DIR="../railway-email-relay-standalone"
echo "📁 Δημιουργία standalone directory: $STANDALONE_DIR"

# Remove if exists
if [ -d "$STANDALONE_DIR" ]; then
    echo "⚠️  Το directory υπάρχει ήδη. Διαγραφή..."
    rm -rf "$STANDALONE_DIR"
fi

# Create fresh directory
mkdir -p "$STANDALONE_DIR"

# Copy all files
echo "📋 Αντιγραφή αρχείων..."
cp server.js "$STANDALONE_DIR/"
cp package.json "$STANDALONE_DIR/"
cp railway.json "$STANDALONE_DIR/"
cp README.md "$STANDALONE_DIR/"
cp .gitignore "$STANDALONE_DIR/"

# Create a git repository
cd "$STANDALONE_DIR"
git init
git add .
git commit -m "Initial commit - Railway email relay service"

echo ""
echo "✅ Standalone deployment directory δημιουργήθηκε: $STANDALONE_DIR"
echo ""
echo "📝 Επόμενα βήματα:"
echo ""
echo "1️⃣  Deploy με Railway CLI:"
echo "    cd $STANDALONE_DIR"
echo "    railway login"
echo "    railway init"
echo "    railway up"
echo "    railway domain"
echo ""
echo "2️⃣  Ή push σε GitHub και deploy με Web UI:"
echo "    cd $STANDALONE_DIR"
echo "    # Δημιούργησε νέο GitHub repo (π.χ. firebed-email-relay)"
echo "    git remote add origin https://github.com/YOUR-USERNAME/firebed-email-relay.git"
echo "    git push -u origin main"
echo "    # Μετά deploy από Railway Web UI → GitHub repo"
echo ""
echo "3️⃣  Configure Firebed_private:"
echo "    - Go to /admin/settings"
echo "    - Select 'Railway Proxy'"
echo "    - Enter Railway URL"
echo "    - Save"
echo ""
echo "🎉 Έτοιμο για deployment!"
