#!/usr/bin/env python3
"""
Upgrade database schema by adding missing columns to existing tables.
This script safely migrates the database without losing data.
"""
import sqlite3
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db

DATABASE_PATH = 'data/app_data.db'

def get_table_columns(conn, table_name):
    """Get list of columns in a table."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return columns

def add_column_if_missing(conn, table_name, column_name, column_type, default_value=None):
    """Add a column to table if it doesn't exist."""
    cursor = conn.cursor()
    columns = get_table_columns(conn, table_name)
    
    if column_name in columns:
        print(f"  ✓ Column '{column_name}' already exists in '{table_name}'")
        return False
    
    default_clause = ""
    if default_value is not None:
        if isinstance(default_value, str):
            default_clause = f" DEFAULT '{default_value}'"
        else:
            default_clause = f" DEFAULT {default_value}"
    
    try:
        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}{default_clause}"
        cursor.execute(sql)
        conn.commit()
        print(f"  ✅ Added column '{column_name}' to '{table_name}'")
        return True
    except sqlite3.OperationalError as e:
        print(f"  ❌ Error adding column: {e}")
        return False

def create_verification_token_table(conn):
    """Create VerificationToken table if it doesn't exist."""
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_token (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token VARCHAR(255) NOT NULL UNIQUE,
                token_type VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES user(id)
            )
        """)
        conn.commit()
        print("  ✅ verification_token table created or already exists")
        return True
    except sqlite3.OperationalError as e:
        print(f"  ❌ Error creating verification_token table: {e}")
        return False

def main():
    print("🔧 Database Schema Upgrade\n")
    
    if not os.path.exists(DATABASE_PATH):
        print(f"❌ Database not found at {DATABASE_PATH}")
        print("Creating new database with Flask-SQLAlchemy...\n")
        
        with app.app_context():
            db.create_all()
            print("✅ New database created successfully")
        return
    
    print(f"Connecting to: {DATABASE_PATH}\n")
    conn = sqlite3.connect(DATABASE_PATH)
    
    try:
        # Add missing columns to user table
        print("📋 Updating 'user' table:")
        add_column_if_missing(conn, 'user', 'email_verified', 'BOOLEAN', 0)
        add_column_if_missing(conn, 'user', 'email_verified_at', 'TIMESTAMP', None)
        
        # Create verification_token table
        print("\n📋 Updating 'verification_token' table:")
        create_verification_token_table(conn)
        
        print("\n✅ Database schema upgrade complete!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1
    finally:
        conn.close()
    
    # Verify with Flask app
    print("\n🔍 Verifying with Flask app:")
    with app.app_context():
        try:
            from models import User, VerificationToken
            
            # Test User columns
            user = User.query.first()
            if user:
                print(f"✅ User table is accessible")
                email_verified = getattr(user, 'email_verified', None)
                print(f"  - Sample user email_verified: {email_verified}")
            
            # Test VerificationToken
            token_count = VerificationToken.query.count()
            print(f"✅ VerificationToken table is accessible ({token_count} tokens)")
            
        except Exception as e:
            print(f"❌ Verification failed: {e}")
            return 1
    
    print("\n✅ All checks passed!")
    return 0

if __name__ == '__main__':
    sys.exit(main())
