"""
Admin Panel Backend Module - User & Group Management
"""
import os
import json
import shutil
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from pathlib import Path
from models import db, User, Group, UserGroup
import firebase_config
from firebase_config import firebase_log_activity

logger = logging.getLogger(__name__)

# ============================================================================
# Admin Authorization
# ============================================================================

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))  # Set in .env


def is_admin(user: Optional[User]) -> bool:
    """Check if user is an admin (either by is_admin flag or ADMIN_USER_ID env)"""
    if not user:
        return False
    
    # First check the is_admin flag on the user model
    if hasattr(user, 'is_admin') and user.is_admin:
        return True
    
    # Fallback to ADMIN_USER_ID env variable for backwards compatibility
    from flask import current_app
    try:
        admin_id = int(current_app.config.get('ADMIN_USER_ID', ADMIN_USER_ID))
    except Exception:
        admin_id = ADMIN_USER_ID
    
    return user.id == admin_id if admin_id > 0 else False


# ============================================================================
# User Management
# ============================================================================

def admin_list_all_users(include_deleted: bool = False) -> List[Dict[str, Any]]:
    """List all users in the system"""
    try:
        users = User.query.all()
        result = []
        
        for user in users:
            result.append({
                'id': user.id,
                'username': user.username,
                'email': getattr(user, 'email', None),
                'firebase_uid': getattr(user, 'pw_hash', None),
                'created_at': str(getattr(user, 'created_at', None)),
                'groups': [{'id': g.id, 'name': g.name} for g in user.groups],
                'group_count': len(user.groups),
                'is_admin': getattr(user, 'is_admin', False),
                'is_admin_of': [g.name for g in user.groups if user.role_for_group(g) == 'admin']
            })
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        return []


def admin_get_user_details(user_id: int) -> Optional[Dict[str, Any]]:
    """Get detailed info about a specific user"""
    try:
        user = User.query.get(user_id)
        if not user:
            return None
        
        groups_info = []
        for g in user.groups:
            role = user.role_for_group(g)
            groups_info.append({
                'id': g.id,
                'name': g.name,
                'data_folder': g.data_folder,
                'role': role
            })
        
        # Calculate total size for user's groups
        total_size = 0
        for g in user.groups:
            data_path = os.path.join(os.getcwd(), 'data', g.data_folder) if getattr(g, 'data_folder', None) else None
            # If the server has no local data for this group, attempt lazy pull from Firebase
            try:
                if getattr(g, 'data_folder', None):
                    firebase_config.ensure_group_data_local(g.data_folder)
                if data_path and os.path.exists(data_path):
                    total_size += _get_folder_size(data_path)
            except Exception:
                continue

        # Fetch recent activity entries related to this user (best-effort)
        try:
            logs = admin_get_activity_logs(limit=200)
            recent = []
            user_keys = {str(user.id), str(getattr(user, 'username', '') or ''), str(getattr(user, 'email', '') or ''), str(getattr(user, 'firebase_uid', '') or '' )}
            for entry in logs:
                uid = str(entry.get('user_id') or '')
                # include if any of the identifying keys match
                if uid in user_keys or any(k and k in uid for k in user_keys):
                    recent.append(entry)
            recent = recent[:50]
        except Exception:
            recent = []

        return {
            'id': user.id,
            'username': user.username,
            'email': getattr(user, 'email', None),
            'created_at': str(getattr(user, 'created_at', None)),
            'groups': groups_info,
            'last_login': str(getattr(user, 'last_login', None)),
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'recent_activity': recent,
        }
    
    except Exception as e:
        logger.error(f"Failed to get user details: {e}")
        return None


def admin_delete_user(user_id: int, current_admin: User) -> Dict[str, Any]:
    """
    Delete a user and handle associated data
    - Remove user from Firebase
    - Clean up local files
    - Log action
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return {'ok': False, 'error': 'User not found'}
        
        if user.id == current_admin.id:
            return {'ok': False, 'error': 'Cannot delete yourself'}
        
        # Protect main admin from deletion
        user_email = getattr(user, 'email', '')
        if user_email == 'adonis.douramanis@gmail.com':
            return {'ok': False, 'error': 'Cannot delete the main admin user'}
        
        username = user.username
        
        # Remove from all groups
        for ug in user.user_groups:
            db.session.delete(ug)
        
        # Try to delete from Firebase
        try:
            fb_user = firebase_config.firebase_get_user_by_email(user.username + "@firebed.local")
            if fb_user:
                firebase_config.firebase_delete_user(fb_user['uid'])
        except Exception as e:
            logger.warning(f"Failed to delete Firebase user: {e}")
        
        # Delete user from DB
        db.session.delete(user)
        db.session.commit()
        
        firebase_log_activity(current_admin.id, "admin", "user_deleted", {
            'deleted_user_id': user_id,
            'deleted_username': username
        })
        
        logger.info(f"Admin deleted user: {username}")
        return {'ok': True, 'message': f'User {username} deleted'}
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete user: {e}")
        return {'ok': False, 'error': str(e)}


# ============================================================================
# Group Management
# ============================================================================

def admin_list_all_groups() -> List[Dict[str, Any]]:
    """List all groups in the system"""
    try:
        groups = Group.query.all()
        result = []
        
        for group in groups:
            member_roles = {}
            for ug in group.user_groups:
                member_roles[ug.user.username] = ug.role
            
            # Attempt lazy-pull if group data missing locally
            data_folder = getattr(group, 'data_folder', None)
            if data_folder:
                try:
                    firebase_config.ensure_group_data_local(data_folder)
                except Exception as e:
                    logger.debug(f"Lazy-pull failed for group {group.name}: {e}")
            
            # Calculate folder size (now that lazy-pull has been attempted)
            folder_size = 0
            if data_folder:
                try:
                    data_path = os.path.join(os.getcwd(), 'data', data_folder)
                    if os.path.exists(data_path):
                        folder_size = _get_folder_size(data_path)
                except Exception as e:
                    logger.debug(f"Failed to calculate folder size for {group.name}: {e}")
            
            result.append({
                'id': group.id,
                'name': group.name,
                'group_name': group.name,  # keep alias for backward compatibility
                'data_folder': group.data_folder,
                'members_count': len(group.user_groups),
                'admins': [u.user.username for u in group.user_groups if u.role == 'admin'],
                'created_at': str(getattr(group, 'created_at', None)),
                'folder_size_mb': round(folder_size / (1024 * 1024), 2)
            })
        
        return result
    
    except Exception as e:
        logger.error(f"Failed to list groups: {e}")
        return []


def admin_get_group_details(group_id: int) -> Optional[Dict[str, Any]]:
    """Get detailed info about a group"""
    try:
        group = Group.query.get(group_id)
        if not group:
            return None
        
        members = []
        for ug in group.user_groups:
            members.append({
                'user_id': ug.user_id,
                'username': ug.user.username,
                'role': ug.role
            })
        
        # Get data size. If local data folder missing, try to pull from Firebase lazily
        data_path = os.path.join(os.getcwd(), 'data', group.data_folder)
        try:
            firebase_config.ensure_group_data_local(group.data_folder)
        except Exception as e:
            logger.debug(f"Lazy-pull failed for group {group.name}: {e}")
        folder_size = _get_folder_size(data_path) if os.path.exists(data_path) else 0
        
        return {
            'id': group.id,
            'name': group.name,
            'data_folder': group.data_folder,
            'members': members,
            'folder_size_mb': round(folder_size / (1024 * 1024), 2),
            'created_at': str(getattr(group, 'created_at', None))
        }
    
    except Exception as e:
        logger.error(f"Failed to get group details: {e}")
        return None


def admin_delete_group(group_id: int, current_admin: User, backup_first: bool = True, active_client_name: str = None) -> Dict[str, Any]:
    """
    Delete a group and its data
    - Backup data if requested
    - Remove from Firebase
    - Delete local files
    """
    try:
        group = Group.query.get(group_id)
        if not group:
            return {'ok': False, 'error': 'Group not found'}
        
        group_name = group.name
        data_folder = group.data_folder
        
        # Create backup if requested and if data folder exists
        backup_path = None
        data_path = os.path.join(os.getcwd(), 'data', data_folder) if data_folder else None
        if backup_first and data_path and os.path.exists(data_path):
            backup_path = admin_backup_group(group_id)
            if not backup_path:
                return {'ok': False, 'error': 'Failed to create backup before deletion'}
        
        # Remove all members
        for ug in group.user_groups:
            db.session.delete(ug)
        
        # Delete from Firebase - all related data
        try:
            firebase_config.firebase_delete_data(f'/groups/{group_name}')
            firebase_config.firebase_delete_data(f'/group_encryption_keys/{group_name}')
            firebase_config.firebase_delete_data(f'/activity_logs/{group_name}')
            firebase_config.firebase_delete_data(f'/receipts/{group_name}')
            firebase_config.firebase_delete_data(f'/group_settings/{group_name}')
            logger.info(f"Deleted all Firebase data for group: {group_name}")
        except Exception as e:
            logger.warning(f"Failed to delete Firebase group data: {e}")
        
        # Delete local folder
        data_path = os.path.join(os.getcwd(), 'data', data_folder)
        if os.path.exists(data_path):
            shutil.rmtree(data_path)
        
        # Delete group from DB
        db.session.delete(group)
        db.session.commit()
        
        group_display = group_name
        if active_client_name:
            group_display = f"{group_name} | {active_client_name}"
        firebase_log_activity(current_admin.id, "admin", "group_deleted", {
            'group_id': group_id,
            'group_name': group_display,
            'backup_path': backup_path
        })
        logger.info(f"Admin deleted group: {group_display}")
        return {
            'ok': True,
            'message': f'Group {group_name} deleted',
            'backup_path': backup_path
        }
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete group: {e}")
        return {'ok': False, 'error': str(e)}


# ============================================================================
# Backup & Restore
# ============================================================================

def admin_backup_group(group_id: int, active_client_name: str = None, auto: bool = False) -> Optional[str]:
    """
    Create a backup of a group's data
    Returns path to backup file
    """
    try:
        group = Group.query.get(group_id)
        if not group:
            return None
        
        # Attempt lazy-pull if data missing locally
        try:
            firebase_config.ensure_group_data_local(group.data_folder)
        except Exception as e:
            logger.debug(f"Lazy-pull failed for backup of {group.name}: {e}")
        
        data_path = os.path.join(os.getcwd(), 'data', group.data_folder)
        if not os.path.exists(data_path):
            logger.warning(f"Group data folder not found after lazy-pull attempt: {data_path}")
            return None
        
        # Create backups folder
        backups_dir = os.path.join(os.getcwd(), 'data', '_backups')
        os.makedirs(backups_dir, exist_ok=True)
        
        # Create timestamped backup
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        backup_name = f"{group.data_folder}_backup_{timestamp}"
        backup_path = os.path.join(backups_dir, backup_name)
        
        # Copy directory
        shutil.copytree(data_path, backup_path)
        
        group_display = group.name
        if active_client_name:
            group_display = f"{group.name} | {active_client_name}"
        logger.info(f"Group backup created: {backup_path} for {group_display}")
        if auto:
            logger.info(f"[AUTO BACKUP] Group: {group_display}, Path: {backup_path}")
        return backup_path
    
    except Exception as e:
        logger.error(f"Failed to backup group {group_id}: {e}")
        return None


def admin_list_backups(group_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """List available backups"""
    try:
        backups_dir = os.path.join(os.getcwd(), 'data', '_backups')
        if not os.path.exists(backups_dir):
            return []
        
        backups = []
        for item in os.listdir(backups_dir):
            item_path = os.path.join(backups_dir, item)
            if os.path.isdir(item_path):
                size = _get_folder_size(item_path)
                stat = os.stat(item_path)
                
                backups.append({
                    'name': item,
                    'path': item_path,
                    'size_mb': round(size / (1024 * 1024), 2),
                    'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        # Sort by creation date descending
        backups.sort(key=lambda x: x['created_at'], reverse=True)
        return backups
    
    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        return []


def admin_list_remote_backups(prefix: Optional[str] = None) -> List[Dict[str, Any]]:
    """List backups stored in Firebase under /backups. Optionally filter by prefix (e.g. group name)."""
    try:
        if not firebase_config.is_firebase_enabled():
            return []

        data = firebase_config.firebase_read_data('/backups') or {}
        results = []

        # data structure is expected to be { category: { timestamp: payload } }
        for cat, entries in data.items():
            if not isinstance(entries, dict):
                continue
            for ts_key, payload in entries.items():
                # build a simple name/path
                name = f"/backups/{cat}/{ts_key}"
                if prefix and prefix not in name:
                    continue
                # attempt to compute an approximate size
                try:
                    size = len(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
                except Exception:
                    size = 0

                created_at = None
                try:
                    # ts_key may be ISO timestamp
                    created_at = ts_key
                except Exception:
                    created_at = ''

                results.append({
                    'name': name,
                    'category': cat,
                    'key': ts_key,
                    'size_bytes': size,
                    'size_mb': round(size / (1024 * 1024), 2),
                    'created_at': created_at
                })

        # sort newest first by created_at (string compare OK for ISO timestamps)
        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return results
    except Exception as e:
        logger.error(f"Failed to list remote backups: {e}")
        return []


def admin_delete_remote_backup(backup_path: str, current_admin: User) -> Dict[str, Any]:
    """Delete a backup entry stored in Firebase. `backup_path` should be like '/backups/<cat>/<key>'"""
    try:
        if not firebase_config.is_firebase_enabled():
            return {'ok': False, 'error': 'Firebase not enabled'}

        # sanitize path: ensure it starts with /backups
        if not backup_path.startswith('/backups'):
            return {'ok': False, 'error': 'Invalid backup path'}

        ok = firebase_config.firebase_delete_data(backup_path)
        if ok:
            firebase_log_activity(current_admin.id, 'admin', 'backup_deleted', {'backup_path': backup_path})
            return {'ok': True, 'message': f'Deleted backup {backup_path}'}
        return {'ok': False, 'error': 'Failed to delete backup in Firebase'}
    except Exception as e:
        logger.error(f"Failed to delete remote backup {backup_path}: {e}")
        return {'ok': False, 'error': str(e)}


def admin_restore_remote_backup(backup_path: str, target_group_id: int, groups_to_restore: Optional[List[str]] = None, current_admin: Optional[User] = None) -> Dict[str, Any]:
    """Restore one or more groups from a Firebase backup entry.

    - `backup_path` : Firebase path like '/backups/<cat>/<key>'
    - `target_group_id` : DB Group id to map single-group restores; ignored when groups_to_restore provided
    - `groups_to_restore` : list of group folder names to restore from the backup; if None and backup contains multiple groups, will try to restore the single group matched by target_group_id
    """
    try:
        if not firebase_config.is_firebase_enabled():
            return {'ok': False, 'error': 'Firebase not enabled'}

        # Read backup data
        data = firebase_config.firebase_read_data(backup_path)
        if not data:
            return {'ok': False, 'error': 'Backup not found or empty'}

        # If groups_to_restore not provided, infer from target_group_id
        restore_groups = []
        if groups_to_restore:
            restore_groups = groups_to_restore
        else:
            group = Group.query.get(target_group_id)
            if not group:
                return {'ok': False, 'error': 'Target group not found and no groups_to_restore provided'}
            # try to find matching entry in backup by folder name
            gf = group.data_folder
            if isinstance(data.get('groups'), dict) and gf in data.get('groups'):
                restore_groups = [gf]
            else:
                # if backup is a direct group backup (not full backup), backup might contain group's keys at top-level
                # try using last path segment of backup_path
                parts = backup_path.strip('/').split('/')
                if len(parts) >= 2:
                    candidate = parts[1]
                    restore_groups = [candidate]

        if not restore_groups:
            return {'ok': False, 'error': 'No groups determined to restore'}

        restored = []
        for gname in restore_groups:
            # If full-backup structure (has 'groups' key)
            if isinstance(data.get('groups'), dict) and gname in data['groups']:
                group_blob = data['groups'][gname]
            else:
                # fallback: top-level payload for single group backups
                # backup path like /backups/<group>/<key>
                group_blob = data if isinstance(data, dict) else None

            if not group_blob:
                continue

            # Write to Firebase groups path
            ok = firebase_config.firebase_import_group_data(gname, group_blob)
            # Also write to local folder
            try:
                local_dir = os.path.join(os.getcwd(), 'data', gname)
                # remove existing local data (safety: keep a pre-restore backup)
                if os.path.exists(local_dir):
                    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                    pre = os.path.join(os.getcwd(), 'data', '_backups', f"{gname}_pre_remote_restore_{timestamp}")
                    shutil.copytree(local_dir, pre)
                    shutil.rmtree(local_dir)
                os.makedirs(local_dir, exist_ok=True)
                # materialize keys as JSON files where appropriate
                if isinstance(group_blob, dict):
                    for k, v in group_blob.items():
                        safe = str(k).lstrip('/').replace('/', '_')
                        target_path = os.path.join(local_dir, f"{safe}.json")
                        try:
                            with open(target_path, 'w', encoding='utf-8') as fh:
                                json.dump(v, fh, ensure_ascii=False, indent=2)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Failed to write local data for restored group {gname}: {e}")

            restored.append(gname)

        if current_admin:
            firebase_log_activity(current_admin.id, 'admin', 'remote_backup_restored', {
                'backup_path': backup_path,
                'restored_groups': restored
            })

        if not restored:
            return {'ok': False, 'error': 'No groups restored'}
        return {'ok': True, 'restored': restored}

    except Exception as e:
        logger.error(f"Failed to restore remote backup {backup_path}: {e}")
        return {'ok': False, 'error': str(e)}


def admin_get_backup_zip(backup_name: str) -> Optional[str]:
    """
    Create a zip archive for a named backup folder and return the zip path.
    The zip will be created alongside the backup folder in the _backups directory.
    """
    try:
        backups_dir = os.path.join(os.getcwd(), 'data', '_backups')
        backup_path = os.path.join(backups_dir, backup_name)
        if not os.path.exists(backup_path):
            logger.warning(f"Backup not found for zipping: {backup_path}")
            return None

        zip_base = os.path.join(backups_dir, f"{backup_name}")
        zip_path = f"{zip_base}.zip"

        # If zip already exists, reuse it
        if os.path.exists(zip_path):
            return zip_path

        # Create an archive (zip)
        shutil.make_archive(zip_base, 'zip', backup_path)
        if os.path.exists(zip_path):
            logger.info(f"Created backup zip: {zip_path}")
            return zip_path
        return None

    except Exception as e:
        logger.error(f"Failed to create zip for backup {backup_name}: {e}")
        return None


def admin_restore_backup(backup_name: str, target_group_id: int, current_admin: User) -> Dict[str, Any]:
    """Restore a group from backup"""
    try:
        group = Group.query.get(target_group_id)
        if not group:
            return {'ok': False, 'error': 'Target group not found'}
        
        backup_path = os.path.join(os.getcwd(), 'data', '_backups', backup_name)
        if not os.path.exists(backup_path):
            return {'ok': False, 'error': 'Backup not found'}
        
        data_path = os.path.join(os.getcwd(), 'data', group.data_folder)
        
        # Create safety backup of current data
        if os.path.exists(data_path):
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            safety_backup = os.path.join(os.getcwd(), 'data', '_backups', f"{group.data_folder}_pre_restore_{timestamp}")
            shutil.copytree(data_path, safety_backup)
            logger.info(f"Safety backup created: {safety_backup}")
        
        # Remove current data
        if os.path.exists(data_path):
            shutil.rmtree(data_path)
        
        # Restore from backup
        shutil.copytree(backup_path, data_path)
        
        firebase_log_activity(current_admin.id, "admin", "group_restored", {
            'group_id': target_group_id,
            'group_name': group.name,
            'backup_name': backup_name
        })
        
        logger.info(f"Group restored from backup: {group.name}")
        return {'ok': True, 'message': f'Group {group.name} restored from {backup_name}'}
    
    except Exception as e:
        logger.error(f"Failed to restore backup: {e}")
        return {'ok': False, 'error': str(e)}


# ============================================================================
# Activity & Traffic Logs
# ============================================================================

def _create_detailed_description(action: str, details: Dict[str, Any]) -> str:
    """Create detailed description in Greek for activity logs"""
    try:
        if action == 'export_bridge':
            # Handle nested details structure for bridge exports
            actual_details = details.get('details', details)
            book_category = actual_details.get('book_category', 'Άγνωστο')
            rows_count = actual_details.get('rows_count', 0)
            file_size_mb = actual_details.get('file_size_mb', 0)
            file_name = actual_details.get('file_name', 'Άγνωστο')
            includes_b_kat = actual_details.get('includes_b_kat', False)
            
            category_name = {
                'A': 'Αρχείο Εσόδων',
                'B': 'Βιβλίο Εσόδων',
                'C': 'Βιβλίο Εξόδων',
                'D': 'Αρχείο Εξόδων',
                'E': 'Βιβλίο Παγίων',
                'Β': 'Β Κατηγορία',
                'Γ': 'Γ Κατηγορία',
                'G': 'Γ Κατηγορία'
            }.get(book_category, f'Κατηγορία {book_category}')
            
            includes_g_kat = actual_details.get('includes_g_kat', False)
            b_kat_text = " (συμπεριλαμβάνει Β' Κατηγορία)" if includes_b_kat else ""
            g_kat_text = " (συμπεριλαμβάνει Γ.ect)" if includes_g_kat else ""
            kat_text = b_kat_text or g_kat_text
            
            # Safely format file_size_mb
            try:
                size_text = f"{float(file_size_mb):.2f}"
            except (ValueError, TypeError):
                size_text = str(file_size_mb)
            
            return f"Λήψη γέφυρας {category_name}{kat_text}. {rows_count} γραμμές, κατηγορία βιβλίων {book_category}, μέγεθος {size_text} MB, όνομα αρχείου: {file_name}"
        
        elif action == 'export_expenses':
            # Handle export_expenses action with enhanced details
            actual_details = details.get('details', details)
            rows_count = actual_details.get('rows_count', 0)
            file_size_mb = actual_details.get('file_size_mb', 0)
            file_name = actual_details.get('file_name', 'Άγνωστο')
            book_category = actual_details.get('book_category', 'mixed')
            
            # Translate book_category to Greek
            category_translations = {
                'invoices': 'Τιμολόγια',
                'expenses': 'Έξοδα',
                'receipts': 'Αποδείξεις',
                'mixed': 'Μικτό'
            }
            category_name = category_translations.get(book_category, book_category)
            
            # Safely format file_size_mb
            try:
                size_text = f"{float(file_size_mb):.2f}"
            except (ValueError, TypeError):
                size_text = str(file_size_mb)
            
            return f"Λήψη εξοδολογίου κατηγορίας {category_name} ({rows_count} γραμμές, {size_text} MB) - {file_name}"
        
        elif action == 'delete_rows':
            # Handle delete rows action
            actual_details = details.get('details', details)
            count = actual_details.get('count', 0)
            excel_path = actual_details.get('excel_path', 'Άγνωστο αρχείο')
            
            return f"Διαγραφή {count} γραμμών από αρχείο: {excel_path}"
        
        elif action in ['user_logged_in', 'login']:
            ip_address = details.get('ip_address', 'Άγνωστο')
            return f"Σύνδεση από IP: {ip_address}"
        
        elif action == 'logout':
            ip_address = details.get('ip_address', 'Άγνωστο')
            return f"Αποσύνδεση από IP: {ip_address}"
        
        elif action in ['user_signup_complete', 'user_registered']:
            ip_address = details.get('ip_address', 'Άγνωστο')
            return f"Εγγραφή νέου χρήστη από IP: {ip_address}"
        
        elif action == 'password_changed':
            return "Αλλαγή κωδικού πρόσβασης"
        
        elif action == 'password_reset_completed':
            return "Ολοκλήρωση επαναφοράς κωδικού μέσω email"
        
        elif action == 'verification_email_sent':
            return "Αποστολή email επαλήθευσης λογαριασμού"
        
        elif action in ['delete_user', 'admin_delete_user']:
            target_user = details.get('target_user_email') or details.get('deleted_user') or 'Άγνωστος'
            admin_text = " (από admin)" if action.startswith('admin_') else ""
            return f"Διαγραφή χρήστη: {target_user}{admin_text}"
        
        elif action in ['delete_backup', 'admin_delete_backup']:
            backup_name = details.get('backup_name') or 'Άγνωστο'
            admin_text = " (από admin)" if action.startswith('admin_') else ""
            return f"Διαγραφή backup: {backup_name}{admin_text}"
        
        elif action in ['send_email', 'admin_send_email']:
            recipient_count = details.get('recipient_count') or details.get('recipients', [])
            if isinstance(recipient_count, list):
                recipient_count = len(recipient_count)
            admin_text = " (από admin)" if action.startswith('admin_') else ""
            return f"Αποστολή email σε {recipient_count} παραλήπτες{admin_text}"
        
        elif action == 'group_deleted':
            group_name = details.get('group_name') or 'Άγνωστο'
            return f"Διαγραφή ομάδας: {group_name}"
        
        elif action == 'group_restored':
            group_name = details.get('group_name') or 'Άγνωστο'
            return f"Επαναφορά ομάδας: {group_name}"
        
        elif action == 'backup_deleted':
            backup_name = details.get('backup_name') or 'Άγνωστο'
            return f"Διαγραφή backup: {backup_name}"
        
        elif action == 'user_deleted':
            return "Διαγραφή λογαριασμού χρήστη"
        
        elif action == 'delete_rows':
            # Handle delete rows action
            actual_details = details.get('details', details)
            count = actual_details.get('count', 0)
            excel_path = actual_details.get('excel_path', 'Άγνωστο αρχείο')
            
            return f"Διαγραφή {count} γραμμών από αρχείο: {excel_path}"
        
        # Default fallback - only use existing description if no custom handling
        description = details.get('description', '')
        if description and action not in ['export_bridge']:  # Don't use existing description for actions we handle
            return description
        
        # If no specific handling, return a generic description
        return f"Ενέργεια: {action}"
        
    except Exception as e:
        logger.error(f"Error creating detailed description for {action}: {e}")
        return f"Ενέργεια: {action}"


def admin_get_activity_logs(group_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Get activity logs from Firebase"""
    try:
        if group_name:
            logs = firebase_config.firebase_get_group_activity_logs(group_name, limit)
        else:
            # Get all activity logs from all groups
            all_logs = []
            try:
                # First try to get the old format (flat structure)
                old_logs = firebase_config.firebase_read_data('/activity_logs') or {}
                if isinstance(old_logs, dict):
                    for group, entries in old_logs.items():
                        if isinstance(entries, dict):
                            for _, entry in entries.items():
                                if isinstance(entry, dict):
                                    all_logs.append(entry)
            except Exception as e:
                logger.debug(f"Could not read old format logs: {e}")

            # Now get logs from new format (nested by group)
            try:
                # Get all groups to know which folders to check
                from models import Group
                groups = Group.query.all()
                for group in groups:
                    folder_name = getattr(group, 'data_folder', None) or group.name
                    if folder_name:
                        group_logs = firebase_config.firebase_get_group_activity_logs(folder_name, limit)
                        all_logs.extend(group_logs)
            except Exception as e:
                logger.debug(f"Could not read new format logs: {e}")

            # Sort all logs by timestamp descending and limit
            all_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            # Deduplicate logs based on unique identifier (timestamp + user_id + action + group)
            seen_keys = set()
            deduped_logs = []
            for log in all_logs:
                # Create unique key from identifying fields
                user_id = log.get('user_id') or log.get('details', {}).get('user_id', '')
                action = log.get('action') or log.get('event_type', '')
                group = log.get('group') or log.get('details', {}).get('group', '')
                timestamp = log.get('timestamp', '')
                
                # Create composite key - use first 19 chars of timestamp to ignore milliseconds
                key = f"{timestamp[:19]}_{user_id}_{action}_{group}"
                
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped_logs.append(log)
            
            logs = deduped_logs[:limit]

        # Format timestamps for all logs
        for entry in logs:
            ts = entry.get('timestamp', '')
            dt = None
            entry['timestamp_fmt'] = ''
            if ts:
                # Try ISO8601
                try:
                    dt = datetime.fromisoformat(ts.replace('Z','+00:00'))
                except Exception:
                    pass
                # Try unix timestamp (int/float)
                if not dt:
                    try:
                        dt = datetime.fromtimestamp(float(ts))
                    except Exception:
                        pass
                # Try common string formats (including timezone offset like +0200)
                if not dt:
                    for fmt in (
                        "%Y-%m-%d %H:%M:%S%z",         # 2025-11-20 13:00:58+0200
                        "%Y-%m-%d %H:%M:%S",           # 2025-11-20 13:00:58
                        "%d/%m/%Y, %I:%M:%S %p",       # 20/11/2025, 01:00:58 PM
                        "%Y-%m-%d"                     # 2025-11-20
                    ):
                        try:
                            dt = datetime.strptime(ts, fmt)
                            break
                        except Exception:
                            continue
                if dt:
                    # Convert to Greek timezone (EET/EEST)
                    from datetime import timezone, timedelta
                    eet = timezone(timedelta(hours=2))  # EET is UTC+2, EEST is UTC+3
                    dt = dt.astimezone(eet)
                    # Format without %-I (not supported on Windows)
                    time_str = dt.strftime('%d/%m/%Y, %I:%M:%S %p').replace('AM','π.μ.').replace('PM','μ.μ.')
                    # Remove leading zero from hour if present
                    entry['timestamp_fmt'] = time_str.replace(' 0', ' ')
                elif ts and 'Invalid' not in ts:
                    entry['timestamp_fmt'] = ts
                else:
                    entry['timestamp_fmt'] = '-'

        # Create formatted logs with Greek details
        formatted = []
        for entry in logs:
            # Extract user and group info
            if 'details' in entry and isinstance(entry['details'], dict):
                details = entry['details']
                user_email = details.get('user_email') or details.get('email') or entry.get('user_id') or '-'
                group = details.get('group') or entry.get('group') or '-'
                action = details.get('action') or entry.get('action') or '-'
                # Create detailed description in Greek
                details_text = _create_detailed_description(action, details)
            else:
                # Handle simple structure
                user_email = entry.get('user_email') or entry.get('user_id') or entry.get('username') or '-'
                action = entry.get('action') or entry.get('message') or entry.get('event') or '-'
                group = entry.get('group') or entry.get('group_name') or '-'
                details_obj = entry.get('details', {})
                if isinstance(details_obj, dict):
                    details_text = _create_detailed_description(action, details_obj)
                else:
                    details_text = str(details_obj) if details_obj else ''
            
            # Translate actions to Greek (keep simple for display)
            action_descriptions = {
                'user_login_attempt': 'Προσπάθεια σύνδεσης',
                'user_logged_in': 'Σύνδεση χρήστη',
                'user_signup_complete': 'Εγγραφή χρήστη',
                'password_changed': 'Αλλαγή κωδικού',
                'password_reset_completed': 'Επαναφορά κωδικού',
                'user_joined_group': 'Συμμετοχή σε ομάδα',
                'user_left_group': 'Αποχώρηση από ομάδα',
                'login': 'Σύνδεση',
                'logout': 'Αποσύνδεση',
                'user_registered': 'Εγγραφή χρήστη',
                'verification_email_sent': 'Αποστολή email επαλήθευσης',
                'delete_user': 'Διαγραφή χρήστη',
                'delete_backup': 'Διαγραφή backup',
                'admin_delete_user': 'Διαγραφή χρήστη (admin)',
                'admin_delete_backup': 'Διαγραφή backup (admin)',
                'send_email': 'Αποστολή email',
                'admin_send_email': 'Αποστολή email (admin)',
                'group_deleted': 'Διαγραφή ομάδας',
                'backup_deleted': 'Διαγραφή backup',
                'group_restored': 'Επαναφορά ομάδας',
                'export_bridge': 'Λήψη γέφυρας',
                'export_expenses': 'Λήψη εξοδολογίου',
                'user_deleted': 'Διαγραφή χρήστη',
                'delete_rows': 'Διαγραφή γραμμών',
            }
            action_display = action_descriptions.get(action, action)
            
            formatted.append({
                'timestamp': entry.get('timestamp_fmt', entry.get('timestamp','')),
                'user_email': user_email,
                'group': group,
                'action': action_display,  # This is the translated Greek action
                'summary': action_display,  # Add summary field for template compatibility
                'details': details_text  # This is the detailed Greek description
            })
        
        return formatted

    except Exception as e:
        logger.error(f"Failed to get activity logs: {e}")
        return []


# ============================================================================
# User Impersonation (for testing/support)
# ============================================================================

def admin_create_impersonation_token(target_user_id: int, current_admin: User, expires_in_minutes: int = 30) -> Optional[str]:
    """
    Create a token that allows admin to impersonate a user
    (useful for debugging issues)
    """
    try:
        target_user = User.query.get(target_user_id)
        if not target_user:
            return None
        
        # Store in cache with expiration
        import secrets
        token = secrets.token_urlsafe(32)
        
        # Store token info (in production, use Redis or similar)
        cache_key = f"impersonate_{token}"
        impersonation_info = {
            'target_user_id': target_user_id,
            'admin_id': current_admin.id,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': datetime.now(timezone.utc).isoformat()  # TODO: implement expiration check
        }
        
        firebase_log_activity(current_admin.id, "admin", "impersonation_created", {
            'target_user_id': target_user_id,
            'target_username': target_user.username
        })
        
        return token
    
    except Exception as e:
        logger.error(f"Failed to create impersonation token: {e}")
        return None


# ============================================================================
# Helper Functions
# ============================================================================

def _get_folder_size(folder_path: str) -> int:
    """Get total size of folder in bytes"""
    total = 0
    try:
        for entry in os.scandir(folder_path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += _get_folder_size(entry.path)
    except Exception as e:
        logger.error(f"Error calculating folder size: {e}")
    
    return total


def admin_compare_backup_with_current(backup_path: str, backup_type: str = 'remote') -> Dict[str, Any]:
    """Compare backup with current state to show differences before restore"""
    try:
        comparison = {
            'backup_info': {
                'path': backup_path,
                'type': backup_type
            },
            'differences': [],
            'summary': {
                'groups_in_backup': 0,
                'groups_in_current': 0,
                'groups_to_add': [],
                'groups_to_update': [],
                'groups_to_remove': []
            }
        }
        
        # Get backup data
        backup_data = None
        if backup_type == 'remote':
            backup_data = firebase_config.firebase_read_data(backup_path)
        elif backup_type == 'local':
            # For local backups, we need to read the backup folder structure
            backups_dir = os.path.join(os.getcwd(), 'data', '_backups')
            backup_full_path = os.path.join(backups_dir, backup_path)
            if os.path.exists(backup_full_path):
                backup_data = {'groups': {}}
                # Read backup folder as a single group
                group_name = os.path.basename(backup_path).replace('_backup_', '').split('_')[0]
                backup_data['groups'][group_name] = {'folder_exists': True}
        
        if not backup_data:
            return {'error': 'Could not read backup data'}
        
        # Get current groups
        current_groups = admin_list_all_groups()
        current_group_names = {g['name'] for g in current_groups}
        
        # Analyze backup structure
        backup_groups = set()
        if 'groups' in backup_data and isinstance(backup_data['groups'], dict):
            backup_groups = set(backup_data['groups'].keys())
        elif backup_type == 'remote':
            # Single group backup - extract group name from path
            parts = backup_path.strip('/').split('/')
            if len(parts) >= 2:
                backup_groups.add(parts[1])
        
        comparison['summary']['groups_in_backup'] = len(backup_groups)
        comparison['summary']['groups_in_current'] = len(current_group_names)
        
        # Find differences
        comparison['summary']['groups_to_add'] = list(backup_groups - current_group_names)
        comparison['summary']['groups_to_update'] = list(backup_groups & current_group_names)
        comparison['summary']['groups_to_remove'] = list(current_group_names - backup_groups)
        
        # Create detailed differences
        for group_name in backup_groups:
            diff = {
                'group_name': group_name,
                'action': 'add' if group_name not in current_group_names else 'update',
                'current_exists': group_name in current_group_names
            }
            
            if group_name in current_group_names:
                # Find current group info
                current_group = next((g for g in current_groups if g['name'] == group_name), None)
                if current_group:
                    diff['current_size_mb'] = current_group.get('folder_size_mb', 0)
                    diff['current_members'] = current_group.get('members_count', 0)
            
            comparison['differences'].append(diff)
        
        return comparison
        
    except Exception as e:
        logger.error(f"Failed to compare backup: {e}")
        return {'error': str(e)}


def admin_get_system_stats() -> Dict[str, Any]:
    """Get overall system statistics"""
    try:
        users = User.query.all()
        groups = Group.query.all()
        
        # Calculate total data size
        data_dir = os.path.join(os.getcwd(), 'data')
        total_size = _get_folder_size(data_dir) if os.path.exists(data_dir) else 0
        
        # Calculate activity in last 24h
        now = datetime.now(timezone.utc)
        activity_24h = 0
        try:
            logs = admin_get_activity_logs(limit=1000)
            for entry in logs:
                ts = entry.get('timestamp') or entry.get('timestamp_fmt')
                dt = None
                if ts and ts != '-':
                    # Try ISO format
                    try:
                        dt = datetime.fromisoformat(ts.replace('Z','+00:00'))
                    except Exception:
                        pass
                    # Try formatted datetime with timezone
                    if not dt:
                        try:
                            # Handle Greek locale AM/PM
                            ts_normalized = ts.replace('π.μ.', 'AM').replace('μ.μ.', 'PM')
                            dt = datetime.strptime(ts_normalized, '%d/%m/%Y, %I:%M:%S %p')
                        except Exception:
                            pass
                    # Try simple datetime
                    if not dt:
                        try:
                            dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                        except Exception:
                            pass
                if dt:
                    # Make timezone-aware if naive
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if (now - dt).total_seconds() <= 86400:
                        activity_24h += 1
        except Exception as e:
            logger.error(f"Failed to calculate 24h activity: {e}")
            pass
        return {
            'total_users': len(users),
            'total_groups': len(groups),
            'total_data_size_mb': round(total_size / (1024 * 1024), 2),
            'activity_24h': activity_24h,
            'timestamp': now.isoformat()
        }
    
    except Exception as e:
        logger.error(f"Failed to get system stats: {e}")
        return {}
