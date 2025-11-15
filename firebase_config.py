"""
Firebase configuration and initialization module
"""
import os
import json
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
from firebase_admin import auth as fb_auth
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
import base64
import time
import threading
from typing import List, Dict
import encryption

# ============================================================================
# Firebase Initialization
# ============================================================================

FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH")
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL")
FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")

_firebase_app = None
_firebase_initialized = False


def init_firebase():
    """Initialize Firebase Admin SDK"""
    global _firebase_app, _firebase_initialized
    
    if _firebase_initialized:
        return True
    
    try:
        if not FIREBASE_CREDENTIALS_PATH:
            logger.warning("FIREBASE_CREDENTIALS_PATH not set - Firebase disabled")
            return False
        
        if not os.path.exists(FIREBASE_CREDENTIALS_PATH):
            logger.warning(f"Firebase credentials file not found: {FIREBASE_CREDENTIALS_PATH}")
            return False
        
        # Initialize Firebase Admin SDK
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        _firebase_app = firebase_admin.initialize_app(
            cred,
            {
                'databaseURL': FIREBASE_DATABASE_URL
            }
        )
        _firebase_initialized = True
        logger.info("Firebase Admin SDK initialized successfully")
        return True
    
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        _firebase_initialized = False
        return False


def is_firebase_enabled() -> bool:
    """Check if Firebase is properly initialized"""
    return _firebase_initialized


# ============================================================================
# Firebase Auth Helpers
# ============================================================================

def firebase_create_user(email: str, password: str, display_name: str = "") -> Optional[Dict[str, Any]]:
    """Create a new user in Firebase Authentication"""
    try:
        if not is_firebase_enabled():
            logger.warning("Firebase not initialized - cannot create user")
            return None
        
        user = fb_auth.create_user(
            email=email,
            password=password,
            display_name=display_name,
            email_verified=False
        )
        
        logger.info(f"Firebase user created: {email} (UID: {user.uid})")
        return {
            'uid': user.uid,
            'email': user.email,
            'display_name': user.display_name
        }
    except Exception as e:
        logger.error(f"Failed to create Firebase user {email}: {e}")
        return None


def firebase_get_user(uid: str) -> Optional[Dict[str, Any]]:
    """Get user info from Firebase"""
    try:
        if not is_firebase_enabled():
            return None
        
        user = fb_auth.get_user(uid)
        return {
            'uid': user.uid,
            'email': user.email,
            'display_name': user.display_name,
            'email_verified': user.email_verified,
            'disabled': user.disabled
        }
    except Exception as e:
        logger.error(f"Failed to get Firebase user {uid}: {e}")
        return None


def firebase_get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Get user info from Firebase by email"""
    try:
        if not is_firebase_enabled():
            return None
        
        user = fb_auth.get_user_by_email(email)
        return {
            'uid': user.uid,
            'email': user.email,
            'display_name': user.display_name,
            'email_verified': user.email_verified,
            'disabled': user.disabled
        }
    except Exception as e:
        logger.error(f"Failed to get Firebase user by email {email}: {e}")
        return None


def firebase_delete_user(uid: str) -> bool:
    """Delete a user from Firebase"""
    try:
        if not is_firebase_enabled():
            return False
        
        fb_auth.delete_user(uid)
        logger.info(f"Firebase user deleted: {uid}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete Firebase user {uid}: {e}")
        return False


def firebase_update_user_password(uid: str, password: str) -> bool:
    """Update user password in Firebase"""
    try:
        if not is_firebase_enabled():
            return False
        
        fb_auth.update_user(uid, password=password)
        logger.info(f"Firebase user password updated: {uid}")
        return True
    except Exception as e:
        logger.error(f"Failed to update Firebase user password {uid}: {e}")
        return False


def firebase_set_custom_claims(uid: str, claims: Dict[str, Any]) -> bool:
    """Set custom claims for a user (useful for role management)"""
    try:
        if not is_firebase_enabled():
            return False
        
        fb_auth.set_custom_user_claims(uid, claims)
        logger.info(f"Custom claims set for user {uid}: {claims}")
        return True
    except Exception as e:
        logger.error(f"Failed to set custom claims for {uid}: {e}")
        return False


# ============================================================================
# Firebase Realtime Database Helpers
# ============================================================================

def firebase_write_data(path: str, data: Dict[str, Any]) -> bool:
    """Write data to Firebase Realtime Database"""
    try:
        if not is_firebase_enabled():
            logger.warning("Firebase not initialized - cannot write data")
            return False
        # sanitize path: remove leading slash and replace illegal characters in each segment
        def _sanitize_path(p: str) -> str:
            if not p:
                return ''
            # strip leading/trailing slashes
            p = p.lstrip('/').rstrip('/')
            parts = [seg for seg in p.split('/') if seg != '']
            safe_parts = []
            for seg in parts:
                # Firebase keys cannot contain . # $ [ ]
                for ch in ['.', '#', '$', '[', ']']:
                    seg = seg.replace(ch, '_')
                safe_parts.append(seg)
            return '/'.join(safe_parts)

        safe_path = _sanitize_path(path)
        ref = db.reference(safe_path)
        ref.set(data)
        logger.debug(f"Data written to Firebase: {path}")
        return True
    except Exception as e:
        logger.error(f"Failed to write data to Firebase at {path}: {e}")
        return False


def firebase_read_data(path: str) -> Optional[Dict[str, Any]]:
    """Read data from Firebase Realtime Database"""
    try:
        if not is_firebase_enabled():
            return None
        
        ref = db.reference(path)
        data = ref.get()
        return data
    except Exception as e:
        logger.error(f"Failed to read data from Firebase at {path}: {e}")
        return None


def firebase_update_data(path: str, data: Dict[str, Any]) -> bool:
    """Update (partial) data in Firebase Realtime Database"""
    try:
        if not is_firebase_enabled():
            return False
        
        ref = db.reference(path)
        ref.update(data)
        logger.debug(f"Data updated in Firebase: {path}")
        return True
    except Exception as e:
        logger.error(f"Failed to update data in Firebase at {path}: {e}")
        return False


def firebase_delete_data(path: str) -> bool:
    """Delete data from Firebase Realtime Database"""
    try:
        if not is_firebase_enabled():
            return False
        
        ref = db.reference(path)
        ref.delete()
        logger.debug(f"Data deleted from Firebase: {path}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete data from Firebase at {path}: {e}")
        return False


def firebase_log_activity(user_id: str, group_name: str, action: str, details: Optional[Dict] = None) -> bool:
    """Log user activity to Firebase for traffic tracking"""
    try:
        if not is_firebase_enabled():
            return False
        
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = {
            'user_id': user_id,
            'group': group_name,
            'action': action,
            'timestamp': timestamp,
            'details': details or {}
        }
        
        # Write to activity log under /activity_logs/{group}/{timestamp}
        # Replace special characters in timestamp for Firebase path compatibility
        safe_timestamp = timestamp.replace(":", "-").replace("+", "_").replace(".", "-")
        path = f'/activity_logs/{group_name}/{safe_timestamp}'
        result = firebase_write_data(path, log_entry)
        return result
    except Exception as e:
        logger.error(f"Failed to log activity to Firebase: {e}")
        return False


def firebase_get_group_activity_logs(group_name: str, limit: int = 100) -> list:
    """Retrieve activity logs for a group"""
    try:
        if not is_firebase_enabled():
            return []
        
        path = f'/activity_logs/{group_name}'
        data = firebase_read_data(path)
        
        if not data:
            return []
        
        # Convert dict to list and sort by timestamp
        logs = []
        for key, value in data.items():
            logs.append(value)
        
        # Sort by timestamp descending (newest first)
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return logs[:limit]
    except Exception as e:
        logger.error(f"Failed to retrieve activity logs for {group_name}: {e}")
        return []


# ============================================================================
# Backup & Export Helpers
# ============================================================================

def firebase_export_group_data(group_name: str) -> Optional[Dict[str, Any]]:
    """Export all data for a group from Firebase"""
    try:
        if not is_firebase_enabled():
            return None
        
        path = f'/groups/{group_name}'
        data = firebase_read_data(path)
        return data
    except Exception as e:
        logger.error(f"Failed to export group data for {group_name}: {e}")
        return None


def firebase_import_group_data(group_name: str, data: Dict[str, Any]) -> bool:
    """Import data for a group to Firebase"""
    try:
        if not is_firebase_enabled():
            return False
        
        path = f'/groups/{group_name}'
        return firebase_write_data(path, data)
    except Exception as e:
        logger.error(f"Failed to import group data for {group_name}: {e}")
        return False


# ============================================================================
# File sync helpers
# ============================================================================

_sync_thread = None
_sync_stop = False
_sync_state_path = os.path.join(os.getcwd(), 'data', '.firebase_sync_state.json')


def _load_sync_state() -> Dict[str, float]:
    try:
        if os.path.exists(_sync_state_path):
            with open(_sync_state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_sync_state(state: Dict[str, float]) -> None:
    try:
        with open(_sync_state_path, 'w', encoding='utf-8') as f:
            json.dump(state, f)
    except Exception:
        pass


def firebase_upload_encrypted_file(group_name: str, rel_path: str, file_bytes: bytes, mtime: float) -> bool:
    """Encrypt file bytes and upload to Firebase under /groups/{group_name}/files/{rel_path}

    Stored payload is base64-encoded ciphertext + metadata.
    """
    try:
        if not is_firebase_enabled():
            return False

        key = encryption._ensure_key()
        if not key:
            logger.error('No master encryption key available for file upload')
            return False

        from cryptography.fernet import Fernet
        cipher = Fernet(key)
        encrypted = cipher.encrypt(file_bytes)
        b64 = base64.urlsafe_b64encode(encrypted).decode('utf-8')

        path = f'/groups/{group_name}/files/{rel_path}'
        data = {
            '_meta': {
                'mtime': mtime,
                'size': len(file_bytes)
            },
            'content': b64
        }
        return firebase_write_data(path, data)
    except Exception as e:
        logger.error(f'Failed to upload encrypted file to Firebase: {e}')
        return False


def _scan_and_sync_data_dir(data_dir: str, group_names: List[str] = None) -> None:
    """Scan data_dir and sync changed files to Firebase. Top-level folders are treated as group names.
    If group_names is provided, restrict to those subfolders.
    """
    state = _load_sync_state()
    new_state: Dict[str, float] = {}

    for root, dirs, files in os.walk(data_dir):
        # determine group name: use first path component under data_dir
        rel_root = os.path.relpath(root, data_dir)
        parts = rel_root.split(os.sep)
        if rel_root == '.' or parts[0] == '.':
            group = '__global__'
        else:
            group = parts[0]

        if group_names and group not in group_names:
            continue

        for fname in files:
            # skip dotfiles and internal state files
            if fname.startswith('.') or fname == '.firebase_sync_state.json':
                continue
            full = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(full)
            except Exception:
                continue

            key = os.path.relpath(full, data_dir)
            new_state[key] = mtime

            if state.get(key) == mtime:
                continue

            # file changed -> upload
            try:
                with open(full, 'rb') as f:
                    fb = f.read()
                rel_path = key.replace('..', '').replace('\\', '/')
                ok = firebase_upload_encrypted_file(group, rel_path, fb, mtime)
                if ok:
                    logger.info(f'Uploaded file to Firebase: {rel_path} (group={group})')
            except Exception as e:
                logger.error(f'Failed to read/upload file {full}: {e}')

    _save_sync_state(new_state)


def _sync_loop(data_dir: str, interval: int = 60):
    global _sync_stop
    while not _sync_stop:
        try:
            _scan_and_sync_data_dir(data_dir)
        except Exception as e:
            logger.error(f'Error during Firebase data sync: {e}')
        time.sleep(interval)


def start_firebase_data_sync(data_dir: str = None, interval: int = 60) -> None:
    """Start background thread to sync data/ to Firebase periodically.
    Call after Firebase initialization.
    """
    global _sync_thread, _sync_stop
    if not is_firebase_enabled():
        return

    if data_dir is None:
        data_dir = os.path.join(os.getcwd(), 'data')

    if _sync_thread and _sync_thread.is_alive():
        return

    _sync_stop = False
    _sync_thread = threading.Thread(target=_sync_loop, args=(data_dir, interval), daemon=True)
    _sync_thread.start()
    logger.info('Started Firebase data sync thread')


def stop_firebase_data_sync() -> None:
    global _sync_stop, _sync_thread
    _sync_stop = True
    if _sync_thread:
        _sync_thread.join(timeout=2)
