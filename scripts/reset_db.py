#!/usr/bin/env python3
"""
Complete database reset and initialization.
Drops all tables and creates fresh ones from models.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db

def reset_database():
    """Drop all tables and recreate from models."""
    with app.app_context():
        print("🔧 Database Reset & Initialization")
        print("=" * 60)
        
        try:
            # Drop all tables
            print("\n1️⃣  Dropping all existing tables...")
            db.drop_all()
            print("   ✅ Tables dropped")
            
            # Create all tables from models
            print("\n2️⃣  Creating tables from models...")
            db.create_all()
            print("   ✅ Tables created")
            
            # Verify User table
            from models import User, VerificationToken, Group
            print("\n3️⃣  Verifying schema...")
            
            # Get User columns
            inspector_result = db.inspect(db.engine)
            user_columns = {c['name']: c['type'] for c in inspector_result.get_columns('user')}
            print(f"   User table columns: {list(user_columns.keys())}")
            
            if 'email_verified' in user_columns and 'email_verified_at' in user_columns:
                print("   ✅ User email_verified fields present")
            else:
                print("   ❌ User email fields missing!")
                return False
            
            # Check VerificationToken table
            token_columns = {c['name']: c['type'] for c in inspector_result.get_columns('verification_token')}
            print(f"   VerificationToken table columns: {list(token_columns.keys())}")
            
            if all(col in token_columns for col in ['token', 'token_type', 'expires_at', 'used']):
                print("   ✅ VerificationToken schema correct")
            else:
                print("   ❌ VerificationToken schema incorrect!")
                return False
            
            print("\n✅ Database reset and initialization complete!")
            return True
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    success = reset_database()
    sys.exit(0 if success else 1)
