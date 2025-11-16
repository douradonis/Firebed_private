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
                'groups': [g.name for g in user.groups],
                'group_count': len(user.groups),
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
            if data_path and os.path.exists(data_path):
                total_size += _get_folder_size(data_path)

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
            
            result.append({
                'id': group.id,
                'name': group.name,
                'group_name': group.name,  # keep alias for backward compatibility
                'data_folder': group.data_folder,
                'members_count': len(group.user_groups),
                'admins': [u.user.username for u in group.user_groups if u.role == 'admin'],
                'created_at': str(getattr(group, 'created_at', None))
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
        
        # Get data size
        data_path = os.path.join(os.getcwd(), 'data', group.data_folder)
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


def admin_delete_group(group_id: int, current_admin: User, backup_first: bool = True) -> Dict[str, Any]:
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
        
        # Delete from Firebase
        try:
            firebase_config.firebase_delete_data(f'/groups/{group_name}')
        except Exception as e:
            logger.warning(f"Failed to delete Firebase group data: {e}")
        
        # Delete local folder
        data_path = os.path.join(os.getcwd(), 'data', data_folder)
        if os.path.exists(data_path):
            shutil.rmtree(data_path)
        
        # Delete group from DB
        db.session.delete(group)
        db.session.commit()
        
        firebase_log_activity(current_admin.id, "admin", "group_deleted", {
            'group_id': group_id,
            'group_name': group_name,
            'backup_path': backup_path
        })
        
        logger.info(f"Admin deleted group: {group_name}")
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

def admin_backup_group(group_id: int) -> Optional[str]:
    """
    Create a backup of a group's data
    Returns path to backup file
    """
    try:
        group = Group.query.get(group_id)
        if not group:
            return None
        
        data_path = os.path.join(os.getcwd(), 'data', group.data_folder)
        if not os.path.exists(data_path):
            logger.warning(f"Group data folder not found: {data_path}")
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
        
        logger.info(f"Group backup created: {backup_path}")
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

def admin_get_activity_logs(group_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Get activity logs from Firebase"""
    try:
        if group_name:
            logs = firebase_config.firebase_get_group_activity_logs(group_name, limit)
        else:
            # Get all logs (from all groups)
            logs = firebase_config.firebase_read_data('/activity_logs') or {}
            # Flatten to list
            flat_logs = []
            for group, entries in logs.items():
                if isinstance(entries, dict):
                    for _, entry in entries.items():
                        flat_logs.append(entry)
            
            # Sort and limit
            flat_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            logs = flat_logs[:limit]
        # If firebase returned no logs (or not configured) fall back to local activity.log files
        if not logs:
            local_logs = []
            data_dir = os.path.join(os.getcwd(), 'data')
            if os.path.exists(data_dir):
                for root, dirs, files in os.walk(data_dir):
                    if 'activity.log' in files:
                        path = os.path.join(root, 'activity.log')
                        try:
                            with open(path, 'r', encoding='utf-8') as fh:
                                lines = fh.readlines()[-limit:]
                                for ln in lines:
                                    ln = ln.strip()
                                    if not ln:
                                        continue
                                    # Expect format: ISO_TIMESTAMP - message
                                    parts = ln.split(' - ', 1)
                                    ts = parts[0] if parts else ''
                                    msg = parts[1] if len(parts) > 1 else ln
                                    local_logs.append({
                                        'timestamp': ts,
                                        'group': os.path.basename(root),
                                        'user_id': '',
                                        'action': 'log_entry',
                                        'details': {'message': msg}
                                    })
                        except Exception:
                            continue
            # sort local logs and limit
            local_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            logs = local_logs[:limit]
        
        return logs or []
    
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


def admin_get_system_stats() -> Dict[str, Any]:
    """Get overall system statistics"""
    try:
        users = User.query.all()
        groups = Group.query.all()
        
        # Calculate total data size
        data_dir = os.path.join(os.getcwd(), 'data')
        total_size = _get_folder_size(data_dir) if os.path.exists(data_dir) else 0
        
        return {
            'total_users': len(users),
            'total_groups': len(groups),
            'total_data_size_mb': round(total_size / (1024 * 1024), 2),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    except Exception as e:
        logger.error(f"Failed to get system stats: {e}")
        return {}
