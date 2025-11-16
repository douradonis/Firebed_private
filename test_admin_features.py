#!/usr/bin/env python
"""
Test admin features: activity logging, remote backups, delete/restore
"""
import os
import json
from datetime import datetime, timezone
from app import app, db
from models import User, Group, UserGroup
from admin_panel import (
    admin_list_all_users,
    admin_list_all_groups,
    admin_delete_user,
    admin_delete_group,
    admin_backup_group,
    admin_list_backups,
    admin_list_remote_backups,
    admin_delete_remote_backup,
    admin_restore_remote_backup,
    admin_get_activity_logs,
)
import firebase_config

def test_activity_logging():
    """Test that activity logs are written locally and to Firebase"""
    print("\n=== Testing Activity Logging ===")
    
    with app.app_context():
        # Test local activity log write
        group_name = "test_group"
        user_id = "test_user_123"
        action = "test_action"
        details = {"key": "value", "timestamp": datetime.now(timezone.utc).isoformat()}
        
        success = firebase_config.firebase_log_activity(user_id, group_name, action, details)
        print(f"Activity logged (success={success})")
        
        # Check if local activity.log exists
        local_log_path = os.path.join(os.getcwd(), 'data', group_name, 'activity.log')
        if os.path.exists(local_log_path):
            with open(local_log_path, 'r') as f:
                lines = f.readlines()
            print(f"Local activity.log exists with {len(lines)} entries")
            # Show last entry
            if lines:
                last = json.loads(lines[-1])
                print(f"  Latest entry: user={last.get('user_id')}, action={last.get('action')}")
        else:
            print(f"Local activity.log not found at {local_log_path}")
        
        # Retrieve logs
        logs = admin_get_activity_logs(group_name)
        print(f"Retrieved {len(logs)} activity logs")
        if logs:
            print(f"  Sample: {logs[0]}")


def test_backup_management():
    """Test local and remote backup operations"""
    print("\n=== Testing Backup Management ===")
    
    with app.app_context():
        # List local backups
        local_backups = admin_list_backups()
        print(f"Local backups: {len(local_backups)} found")
        for b in local_backups[:3]:
            print(f"  - {b['name']} ({b['size_mb']} MB)")
        
        # List remote backups (if Firebase enabled)
        if firebase_config.is_firebase_enabled():
            remote_backups = admin_list_remote_backups()
            print(f"Remote backups: {len(remote_backups)} found")
            for b in remote_backups[:3]:
                print(f"  - {b['name']} ({b['size_mb']} MB)")
        else:
            print("Firebase not enabled - skipping remote backup test")


def test_user_deletion():
    """Test user deletion with logging"""
    print("\n=== Testing User Deletion ===")
    
    with app.app_context():
        # Get admin user (assume exists)
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("No admin user found - skipping user deletion test")
            return
        
        # List existing users
        users = admin_list_all_users()
        print(f"Total users: {len(users)}")
        
        # Create a test user if needed
        test_user = User.query.filter_by(username='test_delete_me').first()
        if not test_user:
            test_user = User(username='test_delete_me', pw_hash='fake_hash')
            db.session.add(test_user)
            db.session.commit()
            print(f"Created test user: {test_user.username}")
        
        # Delete the test user
        result = admin_delete_user(test_user.id, admin)
        print(f"Delete result: {result}")
        
        # Verify deletion
        users = admin_list_all_users()
        print(f"Users after deletion: {len(users)}")


def test_group_deletion():
    """Test group deletion with backup and logging"""
    print("\n=== Testing Group Deletion ===")
    
    with app.app_context():
        # Get admin user
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            print("No admin user found - skipping group deletion test")
            return
        
        # List groups
        groups = admin_list_all_groups()
        print(f"Total groups: {len(groups)}")
        
        # Create a test group if needed
        test_group = Group.query.filter_by(name='test_delete_group').first()
        if not test_group:
            test_group = Group(name='test_delete_group', data_folder='test_delete_group')
            db.session.add(test_group)
            db.session.commit()
            print(f"Created test group: {test_group.name}")
        
        # Create data folder
        data_path = os.path.join(os.getcwd(), 'data', test_group.data_folder)
        os.makedirs(data_path, exist_ok=True)
        with open(os.path.join(data_path, 'sample.txt'), 'w') as f:
            f.write('Sample data')
        
        # Delete the group (with backup)
        result = admin_delete_group(test_group.id, admin, backup_first=True)
        print(f"Delete result: {result}")
        
        # Check backup
        if result.get('backup_path'):
            backup_exists = os.path.exists(result['backup_path'])
            print(f"Backup exists: {backup_exists} ({result['backup_path']})")
        
        # Verify deletion
        groups = admin_list_all_groups()
        print(f"Groups after deletion: {len(groups)}")


if __name__ == '__main__':
    print("Starting admin features tests...")
    print(f"Firebase enabled: {firebase_config.is_firebase_enabled()}")
    
    test_activity_logging()
    test_backup_management()
    test_user_deletion()
    test_group_deletion()
    
    print("\n=== Tests completed ===")
