"""
Admin API Endpoints for Dashboard
Provides JSON API for admin panel operations
"""

import logging
from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
import firebase_config
from firebase_auth_handlers import FirebaseAuthHandler
from models import db, User, Group
import admin_panel
from admin_panel import admin_list_all_users, admin_list_all_groups, admin_get_activity_logs, is_admin

logger = logging.getLogger(__name__)

admin_api_bp = Blueprint('admin_api', __name__, url_prefix='/admin/api')


def _require_admin(f):
    """Decorator to require admin access"""
    def decorated_function(*args, **kwargs):
        if not current_user or not current_user.is_authenticated:
            return jsonify({'error': 'Not authenticated'}), 401
        # Use centralized admin check (supports is_admin flag or ADMIN_USER_ID fallback)
        try:
            if not is_admin(current_user):
                return jsonify({'error': 'Admin access required'}), 403
        except Exception:
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function


@admin_api_bp.route('/users', methods=['GET'])
@login_required
@_require_admin
def api_list_users():
    """Get all users"""
    try:
        users = admin_list_all_users()
        return jsonify({
            'success': True,
            'users': users,
            'count': len(users)
        })
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/users/<uid>', methods=['GET'])
@login_required
@_require_admin
def api_get_user(uid):
    """Get user details"""
    try:
        user = FirebaseAuthHandler.get_user_by_uid(uid)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        return jsonify({
            'success': True,
            'user': user
        })
    except Exception as e:
        logger.error(f"Error getting user {uid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/users/<uid>', methods=['DELETE'])
@login_required
@_require_admin
def api_delete_user(uid):
    """Delete a user"""
    try:
        success, error = FirebaseAuthHandler.delete_user(uid)
        if not success:
            return jsonify({'success': False, 'error': error}), 400
        
        return jsonify({
            'success': True,
            'message': f'User {uid} deleted'
        })
    except Exception as e:
        logger.error(f"Error deleting user {uid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups', methods=['GET'])
@login_required
@_require_admin
def api_list_groups():
    """Get all groups"""
    try:
        groups = admin_list_all_groups()
        return jsonify({
            'success': True,
            'groups': groups,
            'count': len(groups)
        })
    except Exception as e:
        logger.error(f"Error listing groups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups/<group_name>', methods=['GET'])
@login_required
@_require_admin
def api_get_group(group_name):
    """Get group details"""
    try:
        group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
        if not group_data:
            return jsonify({'success': False, 'error': 'Group not found'}), 404
        
        return jsonify({
            'success': True,
            'group': group_data
        })
    except Exception as e:
        logger.error(f"Error getting group {group_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups/<group_name>', methods=['DELETE'])
@login_required
@_require_admin
def api_delete_group(group_name):
    """Delete a group"""
    try:
        # Log activity
        firebase_config.firebase_log_activity(
            current_user.pw_hash or 'admin',
            group_name,
            'admin_group_deleted',
            {'admin_user_id': current_user.id}
        )
        
        # Delete group data
        firebase_config.firebase_delete_data(f'/groups/{group_name}')
        firebase_config.firebase_delete_data(f'/group_encryption_keys/{group_name}')
        firebase_config.firebase_delete_data(f'/activity_logs/{group_name}')
        
        return jsonify({
            'success': True,
            'message': f'Group {group_name} deleted'
        })
    except Exception as e:
        logger.error(f"Error deleting group {group_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups/<int:group_id>', methods=['DELETE'])
@login_required
@_require_admin
def api_delete_group_by_id(group_id):
    """Delete a group by ID using admin_panel function"""
    try:
        result = admin_panel.admin_delete_group(group_id, current_user, backup_first=True)
        if result.get('ok'):
            return jsonify({
                'success': True,
                'message': result.get('message', 'Group deleted successfully'),
                'backup_path': result.get('backup_path')
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 400
    except Exception as e:
        logger.error(f"Error deleting group {group_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/activity', methods=['GET'])
@login_required
@_require_admin
def api_get_activity():
    """Get activity logs"""
    try:
        group_filter = request.args.get('group', '')
        limit = int(request.args.get('limit', 100))
        
        if group_filter:
            logs = firebase_config.firebase_get_group_activity_logs(group_filter, limit=limit)
        else:
            # Get logs from all groups
            logs = []
            groups = admin_list_all_groups()
            for group in groups:
                group_name = group.get('name') or group.get('group_name')
                group_logs = firebase_config.firebase_get_group_activity_logs(group_name, limit=20)
                logs.extend(group_logs)
            
            # Sort by timestamp, most recent first
            logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            logs = logs[:limit]
        
        return jsonify({
            'success': True,
            'logs': logs,
            'count': len(logs)
        })
    except Exception as e:
        logger.error(f"Error getting activity: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/stats', methods=['GET'])
@login_required
@_require_admin
def api_get_stats():
    """Get system statistics"""
    try:
        users = admin_list_all_users()
        groups = admin_list_all_groups()
        
        # Count recent activity (last 24 hours)
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        
        recent_count = 0
        for group in groups:
            group_name = group.get('name') or group.get('group_name')
            logs = firebase_config.firebase_get_group_activity_logs(group_name, limit=100)
            for log in logs:
                try:
                    log_time = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
                    if log_time > yesterday:
                        recent_count += 1
                except:
                    pass
        
        return jsonify({
            'success': True,
            'stats': {
                'total_users': len(users),
                'total_groups': len(groups),
                'recent_activity_24h': recent_count,
                'firebase_enabled': firebase_config.is_firebase_enabled(),
                'timestamp': now.isoformat()
            }
        })
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backup/group/<group_name>', methods=['POST'])
@login_required
@_require_admin
def api_backup_group(group_name):
    """Backup a specific group"""
    try:
        backup_path = f'/backups/{group_name}/{datetime.now(timezone.utc).isoformat()}'
        
        # Backup group data
        group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
        if group_data:
            firebase_config.firebase_write_data(backup_path, group_data)
        
        logger.info(f"Backup created for group {group_name}")
        
        return jsonify({
            'success': True,
            'backup_path': backup_path,
            'message': f'Backup created for {group_name}'
        })
    except Exception as e:
        logger.error(f"Error backing up group {group_name}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500



@admin_api_bp.route('/backup/list', methods=['GET'])
@login_required
@_require_admin
def api_list_remote_backups():
    """List backups stored in Firebase"""
    try:
        prefix = request.args.get('prefix')
        backups = admin_panel.admin_list_remote_backups(prefix)
        return jsonify({'success': True, 'backups': backups})
    except Exception as e:
        logger.error(f"Error listing remote backups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backup', methods=['DELETE'])
@login_required
@_require_admin
def api_delete_remote_backup():
    """Delete a remote backup entry in Firebase. JSON body: {'backup_path': '/backups/...'}"""
    try:
        data = request.json or {}
        path = data.get('backup_path')
        if not path:
            return jsonify({'success': False, 'error': 'backup_path required'}), 400
        
        # If path doesn't start with /backups/, assume it's just the backup name and construct the full path
        if not path.startswith('/backups/'):
            # Try to construct a proper backup path
            if path.startswith('/backups'):
                full_path = path  # Already has /backups prefix
            else:
                full_path = f'/backups/{path}' if '/' not in path else path
        else:
            full_path = path
        
        logger.info(f"Attempting to delete remote backup: {full_path}")
        
        res = admin_panel.admin_delete_remote_backup(full_path, current_user)
        
        if res.get('ok'):
            return jsonify({'success': True, 'message': res.get('message', 'Remote backup deleted successfully')})
        else:
            logger.warning(f"Failed to delete remote backup: {res.get('error')}")
            return jsonify({'success': False, 'error': res.get('error', 'Unknown error')}), 400
    except Exception as e:
        logger.error(f"Error deleting remote backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backup/restore', methods=['POST'])
@login_required
@_require_admin
def api_restore_remote_backup():
    """Restore groups from a remote backup. JSON body: {'backup_path': '/backups/..', 'target_group_id': int, 'groups': [names]}"""
    try:
        data = request.json or {}
        path = data.get('backup_path')
        target_group_id = int(data.get('target_group_id', 0)) if data.get('target_group_id') else None
        groups = data.get('groups')
        if not path:
            return jsonify({'success': False, 'error': 'backup_path required'}), 400
        res = admin_panel.admin_restore_remote_backup(path, target_group_id or 0, groups_to_restore=groups, current_admin=current_user)
        return jsonify({'success': res.get('ok', False), 'restored': res.get('restored', []), 'error': res.get('error')}), (200 if res.get('ok') else 400)
    except Exception as e:
        logger.error(f"Error restoring remote backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backup/all', methods=['POST'])
@login_required
@_require_admin
def api_backup_all():
    """Backup all system data"""
    try:
        backup_timestamp = datetime.now(timezone.utc).isoformat()
        backup_path = f'/backups/full_backup/{backup_timestamp}'
        
        # Backup all groups
        groups = admin_list_all_groups()
        backup_data = {
            'timestamp': backup_timestamp,
            'user_id': current_user.id,
            'groups_count': len(groups),
            'groups': {}
        }
        
        for group in groups:
            group_name = group.get('name') or group.get('group_name')
            group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
            if group_data:
                backup_data['groups'][group['group_name']] = group_data
        
        # Write backup
        firebase_config.firebase_write_data(backup_path, backup_data)
        
        logger.info(f"Full system backup created: {backup_path}")
        
        return jsonify({
            'success': True,
            'backup_path': backup_path,
            'groups_backed_up': len(groups),
            'message': 'Full system backup created'
        })
    except Exception as e:
        logger.error(f"Error backing up system: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/activity/clear', methods=['POST'])
@login_required
@_require_admin
def api_clear_activity():
    """Clear activity logs (dangerous!)"""
    try:
        # Get confirmation from client
        if not request.json or not request.json.get('confirm'):
            return jsonify({'success': False, 'error': 'Confirmation required'}), 400
        
        groups = admin_list_all_groups()
        for group in groups:
            group_name = group.get('name') or group.get('group_name')
            firebase_config.firebase_delete_data(f'/activity_logs/{group_name}')
        
        logger.warning(f"Activity logs cleared by admin {current_user.id}")
        
        return jsonify({
            'success': True,
            'message': 'Activity logs cleared'
        })
    except Exception as e:
        logger.error(f"Error clearing activity: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/group/<group_id>/files', methods=['GET'])
@login_required
@_require_admin
def api_list_group_files(group_id):
    """Get list of files in a group folder (for frontend file browser)"""
    try:
        import os
        from pathlib import Path
        
        # Get group
        group = Group.query.get(group_id)
        if not group:
            return jsonify({'success': False, 'error': 'Group not found'}), 404
        
        group_folder = group.data_folder
        if not group_folder:
            return jsonify({'success': False, 'error': 'Group has no data folder'}), 400
        
        # Ensure data is pulled locally
        try:
            firebase_config.ensure_group_data_local(group_folder)
        except Exception as e:
            logger.warning(f"Could not lazy-pull group data: {e}")
        
        # Build file list
        data_path = os.path.join(current_app.root_path, 'data', group_folder)
        files = []
        
        if os.path.isdir(data_path):
            for root, dirs, filenames in os.walk(data_path):
                rel_root = os.path.relpath(root, data_path)
                if rel_root == '.':
                    rel_root = ''
                
                # Add directories
                for dirname in sorted(dirs):
                    dir_path = os.path.join(root, dirname)
                    rel_path = os.path.join(rel_root, dirname) if rel_root else dirname
                    
                    # Skip hidden and system dirs
                    if dirname.startswith('.') or dirname == '__pycache__':
                        continue
                    
                    files.append({
                        'type': 'folder',
                        'name': dirname,
                        'path': rel_path.replace(os.sep, '/'),
                        'size': None
                    })
                
                # Add files
                for filename in sorted(filenames):
                    if filename.startswith('.'):
                        continue
                    
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.join(rel_root, filename) if rel_root else filename
                    
                    try:
                        size = os.path.getsize(file_path)
                    except:
                        size = 0
                    
                    files.append({
                        'type': 'file',
                        'name': filename,
                        'path': rel_path.replace(os.sep, '/'),
                        'size': size
                    })
        
        return jsonify({
            'success': True,
            'group': {
                'id': group.id,
                'name': group.name,
                'data_folder': group_folder
            },
            'files': files,
            'count': len(files)
        })
    except Exception as e:
        logger.error(f"Error listing group files: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/group/<group_id>/file/<path:file_path>', methods=['GET'])
@login_required
@_require_admin
def api_get_group_file(group_id, file_path):
    """Download or view a file from a group folder"""
    try:
        import os
        from flask import send_file
        
        # Get group
        group = Group.query.get(group_id)
        if not group:
            return jsonify({'success': False, 'error': 'Group not found'}), 404
        
        group_folder = group.data_folder
        if not group_folder:
            return jsonify({'success': False, 'error': 'Group has no data folder'}), 400
        
        # Security: prevent path traversal
        if '..' in file_path or file_path.startswith('/'):
            return jsonify({'success': False, 'error': 'Invalid file path'}), 400
        
        full_path = os.path.join(current_app.root_path, 'data', group_folder, file_path)
        
        # Verify path is within group folder
        real_path = os.path.realpath(full_path)
        real_group_path = os.path.realpath(os.path.join(current_app.root_path, 'data', group_folder))
        
        if not real_path.startswith(real_group_path):
            return jsonify({'success': False, 'error': 'Path traversal not allowed'}), 403
        
        if not os.path.isfile(full_path):
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        # For download
        if request.args.get('download'):
            return send_file(full_path, as_attachment=True, download_name=os.path.basename(file_path))
        
        # For preview/read
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return jsonify({
                'success': True,
                'content': content,
                'type': 'text'
            })
        except:
            # If not text, return as binary for download
            return send_file(full_path, as_attachment=True, download_name=os.path.basename(file_path))
    
    except Exception as e:
        logger.error(f"Error getting group file: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# Enhanced CRUD and Admin Operations
# ============================================================================

def _log_admin_action(action_type: str, target_type: str, target_id: str, details: dict = None):
    """Log an admin action for audit trail"""
    try:
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'admin_user_id': current_user.id,
            'admin_username': current_user.username,
            'action': action_type,
            'target_type': target_type,
            'target_id': target_id,
            'details': details or {},
            'ip_address': request.remote_addr
        }
        firebase_config.firebase_log_activity(
            current_user.pw_hash or 'admin',
            '__admin__',
            f'admin_{action_type}',
            log_entry
        )
        logger.info(f'[ADMIN ACTION] {action_type} on {target_type} {target_id} by {current_user.username}')
    except Exception as e:
        logger.error(f'Failed to log admin action: {e}')


@admin_api_bp.route('/users', methods=['POST'])
@login_required
@_require_admin
def api_create_user():
    """Create a new user"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        username = data.get('username', '').strip()
        
        if not email or not password or not username:
            return jsonify({'success': False, 'error': 'Email, password, and username required'}), 400
        
        # Check if user already exists
        existing = User.query.filter_by(email=email).first()
        if existing:
            return jsonify({'success': False, 'error': 'User already exists'}), 400
        
        # Create user in database
        new_user = User(email=email, username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        # Log action
        _log_admin_action('create_user', 'user', str(new_user.id), {
            'email': email,
            'username': username
        })
        
        return jsonify({
            'success': True,
            'message': f'User {username} created',
            'user': {
                'id': new_user.id,
                'email': new_user.email,
                'username': new_user.username
            }
        })
    except Exception as e:
        logger.error(f'Error creating user: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/users/<int:user_id>', methods=['PUT'])
@login_required
@_require_admin
def api_update_user(user_id):
    """Update user details"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        data = request.get_json()
        changes = {}
        
        # Update email
        if 'email' in data:
            new_email = data['email'].strip()
            if new_email and new_email != user.email:
                existing = User.query.filter_by(email=new_email).first()
                if existing:
                    return jsonify({'success': False, 'error': 'Email already in use'}), 400
                changes['email'] = {'from': user.email, 'to': new_email}
                user.email = new_email
        
        # Update username
        if 'username' in data:
            new_username = data['username'].strip()
            if new_username and new_username != user.username:
                changes['username'] = {'from': user.username, 'to': new_username}
                user.username = new_username
        
        # Update password
        if 'password' in data:
            new_password = data['password'].strip()
            if new_password:
                user.set_password(new_password)
                changes['password'] = 'updated'
        
        # Update is_admin flag
        if 'is_admin' in data:
            old_is_admin = user.is_admin
            user.is_admin = bool(data['is_admin'])
            if old_is_admin != user.is_admin:
                changes['is_admin'] = {'from': old_is_admin, 'to': user.is_admin}
        
        db.session.commit()
        
        # Log action
        _log_admin_action('update_user', 'user', str(user_id), changes)
        
        return jsonify({
            'success': True,
            'message': f'User {user.username} updated',
            'changes': changes,
            'user': {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'is_admin': user.is_admin
            }
        })
    except Exception as e:
        logger.error(f'Error updating user {user_id}: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/users/<int:user_id>', methods=['DELETE'])
@login_required
@_require_admin
def api_delete_user_by_id(user_id):
    """Delete a user by ID"""
    try:
        if user_id == current_user.id:
            return jsonify({'success': False, 'error': 'Cannot delete yourself'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        # Protect main admin from deletion
        user_email = getattr(user, 'email', '')
        if user_email == 'adonis.douramanis@gmail.com':
            return jsonify({'success': False, 'error': 'Cannot delete the main admin user'}), 400
        
        username = user.username
        email = user.email
        firebase_uid = getattr(user, 'pw_hash', None)  # Firebase UID is stored in pw_hash
        
        # Delete from Firebase Authentication if UID exists
        if firebase_uid:
            try:
                import firebase_config
                firebase_config.firebase_delete_user(firebase_uid)
                logger.info(f"Deleted Firebase user: {firebase_uid}")
            except Exception as e:
                logger.warning(f"Failed to delete Firebase user {firebase_uid}: {e}")
        
        # Delete from Firebase Database (user data)
        try:
            import firebase_config
            firebase_config.firebase_delete_data(f'/users/{firebase_uid}')
            firebase_config.firebase_delete_data(f'/user_profiles/{firebase_uid}')
            logger.info(f"Deleted Firebase user data for: {firebase_uid}")
        except Exception as e:
            logger.warning(f"Failed to delete Firebase user data: {e}")
        
        # Remove from all groups in the database
        for group in user.groups:
            group.users.remove(user)
        
        # Delete from database
        db.session.delete(user)
        db.session.commit()
        
        # Log action
        _log_admin_action('delete_user', 'user', str(user_id), {
            'username': username,
            'email': email
        })
        
        return jsonify({
            'success': True,
            'message': f'User {username} deleted'
        })
    except Exception as e:
        logger.error(f'Error deleting user {user_id}: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups/<int:group_id>/members', methods=['GET'])
@login_required
@_require_admin
def api_get_group_members(group_id):
    """Get members of a group"""
    try:
        group = Group.query.get(group_id)
        if not group:
            return jsonify({'success': False, 'error': 'Group not found'}), 404
        
        members = []
        for user in group.users:
            members.append({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_admin': user.is_admin
            })
        
        return jsonify({
            'success': True,
            'group': {
                'id': group.id,
                'name': group.name,
                'data_folder': group.data_folder
            },
            'members': members,
            'count': len(members)
        })
    except Exception as e:
        logger.error(f'Error getting group members: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups/<int:group_id>/members', methods=['POST'])
@login_required
@_require_admin
def api_add_group_member(group_id):
    """Add a member to a group"""
    try:
        group = Group.query.get(group_id)
        if not group:
            return jsonify({'success': False, 'error': 'Group not found'}), 404
        
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'user_id required'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        if user in group.users:
            return jsonify({'success': False, 'error': 'User already in group'}), 400
        
        group.users.append(user)
        db.session.commit()
        
        # Log action
        _log_admin_action('add_group_member', 'group', str(group_id), {
            'user_id': user_id,
            'username': user.username,
            'group_name': group.name
        })
        
        return jsonify({
            'success': True,
            'message': f'User {user.username} added to group {group.name}'
        })
    except Exception as e:
        logger.error(f'Error adding group member: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups/<int:group_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
@_require_admin
def api_remove_group_member(group_id, user_id):
    """Remove a member from a group"""
    try:
        group = Group.query.get(group_id)
        if not group:
            return jsonify({'success': False, 'error': 'Group not found'}), 404
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        if user not in group.users:
            return jsonify({'success': False, 'error': 'User not in group'}), 400
        
        group.users.remove(user)
        db.session.commit()
        
        # Log action
        _log_admin_action('remove_group_member', 'group', str(group_id), {
            'user_id': user_id,
            'username': user.username,
            'group_name': group.name
        })
        
        return jsonify({
            'success': True,
            'message': f'User {user.username} removed from group {group.name}'
        })
    except Exception as e:
        logger.error(f'Error removing group member: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/audit-log', methods=['GET'])
@login_required
@_require_admin
def api_get_audit_log():
    """Get detailed audit log of admin actions"""
    try:
        limit = int(request.args.get('limit', 200))
        admin_user_id = request.args.get('admin_user_id')
        action_type = request.args.get('action')
        
        # Get audit logs from Firebase
        logs = firebase_config.firebase_get_group_activity_logs('__admin__', limit=limit)
        
        # Filter if needed
        if admin_user_id:
            logs = [log for log in logs if log.get('details', {}).get('admin_user_id') == int(admin_user_id)]
        
        if action_type:
            logs = [log for log in logs if action_type in log.get('event_type', '')]
        
        return jsonify({
            'success': True,
            'logs': logs,
            'count': len(logs)
        })
    except Exception as e:
        logger.error(f'Error getting audit log: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/user-actions/<int:user_id>', methods=['GET'])
@login_required
@_require_admin
def api_get_user_actions(user_id):
    """Get all actions performed by a specific user"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        limit = int(request.args.get('limit', 100))
        
        # Get all activity logs for this user across groups
        all_logs = []
        groups = Group.query.filter(Group.users.any(id=user_id)).all()
        
        for group in groups:
            group_logs = firebase_config.firebase_get_group_activity_logs(group.name, limit=limit)
            all_logs.extend(group_logs)
        
        # Sort by timestamp, most recent first
        all_logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        all_logs = all_logs[:limit]
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email
            },
            'actions': all_logs,
            'count': len(all_logs)
        })
    except Exception as e:
        logger.error(f'Error getting user actions: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# Additional Endpoints for Unified Dashboard
# ============================================================================

@admin_api_bp.route('/activity-logs', methods=['GET'])
@login_required
@_require_admin
def api_activity_logs():
    """Get activity logs with filtering"""
    try:
        group_filter = request.args.get('group', '')
        action_filter = request.args.get('action', '')
        limit = int(request.args.get('limit', 100))
        
        logs = admin_panel.admin_get_activity_logs(group_filter if group_filter else None, limit)
        
        # Filter by action if provided
        if action_filter:
            logs = [log for log in logs if action_filter.lower() in (log.get('action') or '').lower()]
        
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        logger.error(f"Error getting activity logs: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/users/<int:user_id>', methods=['GET'])
@login_required
@_require_admin
def api_get_user_detail(user_id):
    """Get detailed info about a specific user"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
        user_detail = admin_panel.admin_get_user_details(user_id)
        if not user_detail:
            return jsonify({'success': False, 'error': 'Could not load user details'}), 404
        
        return jsonify({'success': True, 'user': user_detail})
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/groups/<int:group_id>', methods=['GET'])
@login_required
@_require_admin
def api_get_group_detail(group_id):
    """Get detailed info about a specific group"""
    try:
        group = Group.query.get(group_id)
        if not group:
            return jsonify({'success': False, 'error': 'Group not found'}), 404
        
        group_detail = admin_panel.admin_get_group_details(group_id)
        if not group_detail:
            return jsonify({'success': False, 'error': 'Could not load group details'}), 404
        
        return jsonify({'success': True, 'group': group_detail})
    except Exception as e:
        logger.error(f"Error getting group {group_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backups', methods=['GET'])
@login_required
@_require_admin
def api_list_backups():
    """List all local backups"""
    try:
        backups = admin_panel.admin_list_backups()
        return jsonify({'success': True, 'backups': backups})
    except Exception as e:
        logger.error(f"Error listing backups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backups/restore/<path:backup_path>', methods=['POST'])
@login_required
@_require_admin
def api_restore_backup_by_path(backup_path):
    """Restore a backup by its path (handles both local and remote)"""
    try:
        data = request.json or {}
        backup_type = data.get('type', 'remote')
        
        if backup_type == 'remote':
            # For remote backups, backup_path is the Firebase path
            result = admin_panel.admin_restore_remote_backup(
                backup_path, 
                target_group_id=1,  # Will be determined by backend
                current_admin=current_user
            )
        else:
            # For local backups, find the first available group to restore to
            groups = admin_panel.admin_list_all_groups()
            if not groups:
                return jsonify({'success': False, 'error': 'No groups available for restore'}), 400
            
            result = admin_panel.admin_restore_backup(
                backup_path, 
                groups[0]['id'],  # Use first available group
                current_user
            )
        
        return jsonify({
            'success': result.get('ok', False),
            'message': result.get('message', ''),
            'error': result.get('error', ''),
            'restored': result.get('restored', [])
        })
    except Exception as e:
        logger.error(f"Error restoring backup {backup_path}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backups/local', methods=['DELETE'])
@login_required
@_require_admin
def api_delete_local_backup():
    """Delete a local backup. JSON body: {'backup_name': 'name'}"""
    try:
        data = request.json or {}
        backup_name = data.get('backup_name')
        if not backup_name:
            return jsonify({'success': False, 'error': 'backup_name required'}), 400
        
        # Delete local backup
        import os
        import shutil
        backups_dir = os.path.join(os.getcwd(), 'data', '_backups')
        backup_path = os.path.join(backups_dir, backup_name)
        
        if not os.path.exists(backup_path):
            return jsonify({'success': False, 'error': 'Backup not found'}), 404
        
        # Security check - make sure path is within backups directory
        real_backup_path = os.path.realpath(backup_path)
        real_backups_dir = os.path.realpath(backups_dir)
        
        if not real_backup_path.startswith(real_backups_dir):
            return jsonify({'success': False, 'error': 'Invalid backup path'}), 400
        
        # Delete the backup
        if os.path.isdir(backup_path):
            shutil.rmtree(backup_path)
        elif os.path.isfile(backup_path):
            os.remove(backup_path)
        
        # Log the action
        _log_admin_action('delete_backup', 'local_backup', backup_name)
        
        return jsonify({'success': True, 'message': f'Backup {backup_name} deleted successfully'})
        
    except Exception as e:
        logger.error(f"Error deleting local backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backups/local', methods=['GET'])
@login_required
@_require_admin
def api_list_local_backups():
    """List only local server backups"""
    try:
        backups = admin_panel.admin_list_backups()
        return jsonify({'success': True, 'backups': backups, 'type': 'local'})
    except Exception as e:
        logger.error(f"Error listing local backups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backups/remote', methods=['GET'])
@login_required
@_require_admin
def api_list_remote_backups_only():
    """List only Firebase remote backups"""
    try:
        prefix = request.args.get('prefix')
        backups = admin_panel.admin_list_remote_backups(prefix)
        return jsonify({'success': True, 'backups': backups, 'type': 'remote'})
    except Exception as e:
        logger.error(f"Error listing remote backups: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backup/compare', methods=['POST'])
@login_required
@_require_admin
def api_compare_backup():
    """Compare current state with backup for preview before restore"""
    try:
        data = request.json or {}
        backup_path = data.get('backup_path')
        backup_type = data.get('type', 'remote')  # 'local' or 'remote'
        
        if not backup_path:
            return jsonify({'success': False, 'error': 'backup_path required'}), 400
        
        comparison = admin_panel.admin_compare_backup_with_current(backup_path, backup_type)
        return jsonify({'success': True, 'comparison': comparison})
    except Exception as e:
        logger.error(f"Error comparing backup: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backups/local/<path:backup_name>', methods=['DELETE'])
@login_required
@_require_admin
def api_delete_local_backup(backup_name):
    """Delete a local backup"""
    try:
        import os
        import shutil
        import urllib.parse
        
        # Decode URL-encoded backup name
        decoded_backup_name = urllib.parse.unquote(backup_name)
        
        backups_dir = os.path.join(os.getcwd(), 'data', '_backups')
        backup_path = os.path.join(backups_dir, decoded_backup_name)
        
        logger.info(f"Attempting to delete local backup: {backup_path}")
        
        if not os.path.exists(backup_path):
            # Also try without decoding in case the name is already correct
            backup_path_alt = os.path.join(backups_dir, backup_name)
            if not os.path.exists(backup_path_alt):
                logger.warning(f"Backup not found: {backup_path} or {backup_path_alt}")
                return jsonify({'success': False, 'error': f'Backup not found: {decoded_backup_name}'}), 404
            backup_path = backup_path_alt
        
        # Safety check - ensure it's within backups directory
        real_backup_path = os.path.realpath(backup_path)
        real_backups_dir = os.path.realpath(backups_dir)
        
        if not real_backup_path.startswith(real_backups_dir):
            return jsonify({'success': False, 'error': 'Invalid backup path - security violation'}), 400
        
        # Delete the backup
        try:
            if os.path.isdir(backup_path):
                shutil.rmtree(backup_path)
                logger.info(f"Deleted backup directory: {backup_path}")
            else:
                os.remove(backup_path)
                logger.info(f"Deleted backup file: {backup_path}")
        except Exception as delete_error:
            logger.error(f"Failed to delete backup file/directory: {delete_error}")
            return jsonify({'success': False, 'error': f'Failed to delete backup: {str(delete_error)}'}), 500
        
        # Log action
        _log_admin_action('delete_local_backup', 'backup', decoded_backup_name)
        
        return jsonify({
            'success': True,
            'message': f'Local backup {decoded_backup_name} deleted successfully'
        })
    except Exception as e:
        logger.error(f'Error deleting local backup {backup_name}: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_api_bp.route('/backup/restore/local', methods=['POST'])
@login_required
@_require_admin
def api_restore_local_backup():
    """Restore from a local backup"""
    try:
        data = request.json or {}
        backup_name = data.get('backup_name')
        target_group_id = data.get('target_group_id', 1)  # Default to first available group
        
        if not backup_name:
            return jsonify({'success': False, 'error': 'backup_name required'}), 400
        
        # Find a suitable group or create one
        from models import Group
        group = Group.query.first()
        if not group:
            return jsonify({'success': False, 'error': 'No groups available for restore'}), 400
        
        result = admin_panel.admin_restore_backup(backup_name, group.id, current_user)
        
        return jsonify({
            'success': result['ok'],
            'message': result.get('message'),
            'error': result.get('error')
        })
    except Exception as e:
        logger.error(f'Error restoring local backup: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
