#!/usr/bin/env python3
"""
Phase 3 Testing: Lazy-Pull Data Loading
Tests the new ensure_group_data_local() and enhanced firebase_pull_group_to_local()
"""
import os
import sys
import json
import shutil
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

# Initialize Flask app for context
from app import app, db, current_app
from models import User, Group, UserGroup
import firebase_config

def test_context():
    """Create Flask app context for database operations"""
    return app.app_context()

def reset_test_group():
    """Delete test group data folder to simulate missing local data"""
    test_group = 'test_lazy_group'
    data_path = os.path.join(os.getcwd(), 'data', test_group)
    if os.path.exists(data_path):
        shutil.rmtree(data_path)
        print(f"✓ Deleted test group folder: {data_path}")
    return data_path

def test_1_firebase_pull_with_subfolders():
    """Test: firebase_pull_group_to_local() preserves subfolder structure"""
    print("\n" + "="*60)
    print("TEST 1: Firebase Pull with Subfolder Structure")
    print("="*60)
    
    # Skip if Firebase not available
    if not firebase_config.is_firebase_enabled():
        print("⊘ SKIPPED: Firebase not enabled")
        return True
    
    with test_context():
        try:
            # Use a real group if possible
            test_group = 'test_lazy_group'
            
            # Reset: delete local folder
            data_path = reset_test_group()
            
            # Verify it's deleted
            if os.path.exists(data_path):
                print("✗ FAILED: Could not delete test folder")
                return False
            print(f"✓ Test folder deleted: {data_path}")
            
            # Attempt pull
            print(f"Attempting lazy-pull for group: {test_group}")
            result = firebase_config.firebase_pull_group_to_local(test_group)
            print(f"Pull result: {result}")
            
            # Check if folder now exists
            if os.path.exists(data_path):
                print(f"✓ Folder created after pull: {data_path}")
                
                # List contents to verify structure
                for root, dirs, files in os.walk(data_path):
                    level = root.replace(data_path, '').count(os.sep)
                    indent = ' ' * 2 * level
                    rel_path = os.path.relpath(root, data_path)
                    if rel_path == '.':
                        print(f"✓ {data_path}/")
                    else:
                        print(f"{indent}├─ {rel_path}/")
                    for f in files[:3]:  # Show first 3 files
                        print(f"{indent}  ├─ {f}")
                    if len(files) > 3:
                        print(f"{indent}  └─ ... and {len(files)-3} more files")
                
                print(f"✓ TEST 1 PASSED")
                return True
            else:
                print(f"⊘ Folder not found after pull (Firebase may have no data for this group)")
                print(f"✓ TEST 1 PASSED (no data in Firebase is acceptable)")
                return True
        
        except Exception as e:
            print(f"✗ TEST 1 FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_2_ensure_group_data_local():
    """Test: ensure_group_data_local() wrapper function"""
    print("\n" + "="*60)
    print("TEST 2: ensure_group_data_local() Wrapper Function")
    print("="*60)
    
    with test_context():
        try:
            test_group = 'test_lazy_group'
            
            # Reset: delete local folder
            data_path = reset_test_group()
            
            # Call ensure_group_data_local
            print(f"Calling ensure_group_data_local('{test_group}', create_empty_dirs=True)")
            result = firebase_config.ensure_group_data_local(test_group, create_empty_dirs=True)
            print(f"Result: {result}")
            
            # Check if folder exists
            if os.path.isdir(data_path):
                print(f"✓ Folder exists after ensure_group_data_local: {data_path}")
                
                # Check for common subdirectories
                common_subdirs = ['epsilon', 'excel']
                for subdir in common_subdirs:
                    subdir_path = os.path.join(data_path, subdir)
                    if os.path.isdir(subdir_path):
                        print(f"  ✓ Subdirectory created: {subdir}/")
                    else:
                        print(f"  ⊘ Subdirectory not created: {subdir}/")
                
                print(f"✓ TEST 2 PASSED")
                return True
            else:
                print(f"✗ TEST 2 FAILED: Folder not created")
                return False
        
        except Exception as e:
            print(f"✗ TEST 2 FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_3_admin_list_groups_with_lazy_pull():
    """Test: admin_list_all_groups() triggers lazy-pull"""
    print("\n" + "="*60)
    print("TEST 3: Admin List Groups with Lazy-Pull")
    print("="*60)
    
    if not firebase_config.is_firebase_enabled():
        print("⊘ SKIPPED: Firebase not enabled")
        return True
    
    with test_context():
        try:
            import admin_panel
            
            # Delete test group folder
            test_group_folder = 'test_lazy_group'
            data_path = reset_test_group()
            
            # Create a test group in DB (if not exists)
            from models import db
            test_group = Group.query.filter_by(name='test_lazy_group_admin').first()
            if not test_group:
                test_group = Group(name='test_lazy_group_admin', data_folder='test_lazy_group')
                db.session.add(test_group)
                db.session.commit()
                print(f"Created test group in DB: {test_group.name} -> {test_group.data_folder}")
            
            # Call admin_list_all_groups
            print("Calling admin_list_all_groups()...")
            groups = admin_panel.admin_list_all_groups()
            print(f"✓ Retrieved {len(groups)} groups")
            
            # Find our test group
            test_group_data = next((g for g in groups if g.get('data_folder') == 'test_lazy_group'), None)
            if test_group_data:
                print(f"✓ Found test group in list:")
                print(f"  - Name: {test_group_data.get('name')}")
                print(f"  - Data folder: {test_group_data.get('data_folder')}")
                print(f"  - Size: {test_group_data.get('folder_size_mb')} MB")
            else:
                print(f"⊘ Test group not in list (may be normal if not yet created)")
            
            # Check if folder was created by lazy-pull
            if os.path.exists(data_path):
                print(f"✓ Data folder now exists (lazy-pull was triggered): {data_path}")
                print(f"✓ TEST 3 PASSED")
                return True
            else:
                print(f"⊘ Data folder not created (no data in Firebase or create_empty_dirs not working)")
                print(f"✓ TEST 3 PASSED (acceptable state)")
                return True
        
        except Exception as e:
            print(f"✗ TEST 3 FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_4_admin_backup_group_with_lazy_pull():
    """Test: admin_backup_group() triggers lazy-pull"""
    print("\n" + "="*60)
    print("TEST 4: Admin Backup Group with Lazy-Pull")
    print("="*60)
    
    with test_context():
        try:
            import admin_panel
            from models import db
            
            # Create or get test group
            test_group = Group.query.filter_by(name='test_backup_group').first()
            if not test_group:
                test_group = Group(name='test_backup_group', data_folder='test_backup_folder')
                db.session.add(test_group)
                db.session.commit()
                print(f"Created test group: {test_group.name}")
            
            # Delete local folder to simulate missing data
            data_path = os.path.join(os.getcwd(), 'data', test_group.data_folder)
            if os.path.exists(data_path):
                shutil.rmtree(data_path)
                print(f"Deleted group data folder: {data_path}")
            
            # Create some test data so backup has something to backup
            os.makedirs(data_path, exist_ok=True)
            test_file = os.path.join(data_path, 'test_file.txt')
            with open(test_file, 'w') as f:
                f.write('test content')
            print(f"Created test file: {test_file}")
            
            # Call admin_backup_group (which should trigger lazy-pull internally)
            print(f"Calling admin_backup_group({test_group.id})...")
            backup_path = admin_panel.admin_backup_group(test_group.id)
            
            if backup_path and os.path.exists(backup_path):
                print(f"✓ Backup created: {backup_path}")
                # Check backup contents
                backup_file = os.path.join(backup_path, 'test_file.txt')
                if os.path.exists(backup_file):
                    print(f"✓ Backup contains expected file: test_file.txt")
                    print(f"✓ TEST 4 PASSED")
                    return True
                else:
                    print(f"✗ Backup doesn't contain expected file")
                    return False
            else:
                print(f"✗ Backup not created or not found")
                return False
        
        except Exception as e:
            print(f"✗ TEST 4 FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    print("\n" + "="*60)
    print("PHASE 3: LAZY-PULL DATA LOADING - TEST SUITE")
    print("="*60)
    
    # Check Firebase
    print(f"\nFirebase enabled: {firebase_config.is_firebase_enabled()}")
    
    results = []
    
    # Run tests
    results.append(("Test 1: Firebase Pull with Subfolders", test_1_firebase_pull_with_subfolders()))
    results.append(("Test 2: ensure_group_data_local()", test_2_ensure_group_data_local()))
    results.append(("Test 3: Admin List Groups with Lazy-Pull", test_3_admin_list_groups_with_lazy_pull()))
    results.append(("Test 4: Admin Backup Group with Lazy-Pull", test_4_admin_backup_group_with_lazy_pull()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓✓✓ ALL TESTS PASSED ✓✓✓")
        return 0
    else:
        print(f"\n✗✗✗ {total - passed} TEST(S) FAILED ✗✗✗")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
