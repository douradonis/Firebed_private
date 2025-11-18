#!/usr/bin/env python3
"""
Create test users for development.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from models import db, User, Group

def create_test_users():
    """Create admin and regular test users."""
    with app.app_context():
        print("👥 Creating Test Users")
        print("=" * 60)
        
        # Clear existing test users
        User.query.filter_by(username='admin').delete()
        User.query.filter_by(username='testuser1').delete()
        User.query.filter_by(username='testuser2').delete()
        db.session.commit()
        
        # Create admin user
        admin = User(username='admin')
        admin.email = 'admin@example.com'
        admin.set_password('admin123')
        admin.is_admin = True
        db.session.add(admin)
        print("✅ Admin user created:")
        print(f"   Username: admin")
        print(f"   Password: admin123")
        print(f"   Email: admin@example.com")
        
        # Create regular test users
        user1 = User(username='testuser1')
        user1.email = 'testuser1@example.com'
        user1.set_password('test123')
        db.session.add(user1)
        print("\n✅ Test user 1 created:")
        print(f"   Username: testuser1")
        print(f"   Password: test123")
        print(f"   Email: testuser1@example.com")
        
        user2 = User(username='testuser2')
        user2.email = 'testuser2@example.com'
        user2.set_password('test123')
        db.session.add(user2)
        print("\n✅ Test user 2 created:")
        print(f"   Username: testuser2")
        print(f"   Password: test123")
        print(f"   Email: testuser2@example.com")
        
        db.session.commit()
        
        print("\n" + "=" * 60)
        print("✅ Test users created successfully!")
        print("\nYou can now log in with these credentials.")
        print("Use admin account for testing admin panel features.")

if __name__ == '__main__':
    create_test_users()
