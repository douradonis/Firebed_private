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
        res = admin_panel.admin_delete_remote_backup(path, current_user)
        return jsonify({'success': res.get('ok', False), 'message': res.get('message'), 'error': res.get('error')}), (200 if res.get('ok') else 400)
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

