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
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = {
            'user_id': user_id,
            'group': group_name,
            'action': action,
            'timestamp': timestamp,
            'details': details or {}
        }

        # Determine the folder to use for logs
        # Try to get data_folder from Group model if group_name matches a group
        folder_name = group_name
        try:
            # Lazy import to avoid circular dependencies
            from models import Group
            grp = Group.query.filter_by(name=group_name).first()
            if grp and getattr(grp, 'data_folder', None):
                folder_name = grp.data_folder
        except Exception:
            # If we can't query, fall back to group_name
            pass

        wrote_any = False

        # Attempt to write to Firebase if enabled
        try:
            if is_firebase_enabled():
                # Write to activity log under /activity_logs/{group}/{timestamp}
                # Replace special characters in timestamp for Firebase path compatibility
                safe_timestamp = timestamp.replace(":", "-").replace("+", "_").replace(".", "-")
                path = f'/activity_logs/{folder_name}/{safe_timestamp}'
                if firebase_write_data(path, log_entry):
                    wrote_any = True
        except Exception:
            # keep going; we'll still write a local log
            pass

        # Also append to a local activity.log per-group for offline inspection and admin panel fallback
        try:
            data_dir = os.path.join(os.getcwd(), 'data')
            os.makedirs(data_dir, exist_ok=True)
            
            group_dir = os.path.join(data_dir, str(folder_name) if folder_name else 'global')
            os.makedirs(group_dir, exist_ok=True)
            activity_path = os.path.join(group_dir, 'activity.log')
            with open(activity_path, 'a', encoding='utf-8') as fh:
                # store a compact JSON line for easier parsing
                fh.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            wrote_any = True
        except Exception:
            pass

        return wrote_any
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


def _maybe_decompress_blob(obj: Any) -> Any:
    """If object is a compressed payload created by firebase_write_compressed, decompress it."""
    try:
        if isinstance(obj, dict) and obj.get('_compressed'):
            import gzip
            b64 = obj.get('content') or ''
            raw = base64.urlsafe_b64decode(b64.encode('utf-8'))
            data = gzip.decompress(raw)
            return json.loads(data.decode('utf-8'))
    except Exception:
        pass
    return obj


def firebase_read_data_compressed(path: str) -> Optional[Dict[str, Any]]:
    """Read data and automatically decompress if stored as compressed blob."""
    try:
        data = firebase_read_data(path)
        if data is None:
            return None
        # If top-level object is compressed blob
        decompressed = _maybe_decompress_blob(data)
        if decompressed is not data:
            return decompressed

        # Walk dict and decompress any nested compressed blobs (shallow)
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                out[k] = _maybe_decompress_blob(v)
            return out
        return data
    except Exception as e:
        logger.error(f"Failed to read compressed data from Firebase at {path}: {e}")
        return None


def firebase_write_compressed(path: str, data: Dict[str, Any], compress_threshold: int = 5 * 1024) -> bool:
    """Write data to Firebase; if serialized size > threshold, gzip-compress and base64 encode it.
    Stores compressed payload under the same path as {'_compressed': True, 'content': '<b64>'}.
    """
    try:
        text = json.dumps(data, ensure_ascii=False)
        raw = text.encode('utf-8')
        if len(raw) <= compress_threshold:
            return firebase_write_data(path, data)

        import gzip
        compressed = gzip.compress(raw)
        b64 = base64.urlsafe_b64encode(compressed).decode('utf-8')
        payload = {'_compressed': True, 'content': b64}
        return firebase_write_data(path, payload)
    except Exception as e:
        logger.error(f"Failed to write compressed data to Firebase at {path}: {e}")
        return False


def firebase_push_group_files(group_name: str, local_data_root: str = None) -> bool:
    """Upload group files from local data/ folder to Firebase /groups/{group_name}/files.
    
    Also detects and removes files from Firebase that have been deleted locally.
    This is called on logout to sync any changes made to files back to Firebase.
    Files are read from data/{group_name}/ (and subdirectories), encrypted, and uploaded.
    
    Returns True if push succeeded or no files found.
    """
    try:
        if not is_firebase_enabled():
            logger.warning('[PUSH] Firebase not enabled; cannot push group files')
            return False

        if local_data_root is None:
            local_data_root = os.path.join(os.getcwd(), 'data')

        source_dir = os.path.join(local_data_root, group_name)
        if not os.path.isdir(source_dir):
            logger.warning('[PUSH] Group directory not found: %s', source_dir)
            return True  # No error, just nothing to push

        # Get encryption key
        fernet_key = encryption._ensure_key()
        if not fernet_key:
            logger.error('[PUSH] No Fernet key available; cannot encrypt files')
            return False

        from cryptography.fernet import Fernet
        cipher = Fernet(fernet_key)
        
        files_uploaded = 0
        files_failed = 0
        files_deleted = 0
        
        # Build set of local file keys (what should exist in Firebase)
        local_file_keys = set()
        
        # Scan all files in the source directory (including subdirectories)
        for root, dirs, files in os.walk(source_dir):
            for fname in files:
                try:
                    # Skip certain files
                    if fname.startswith('.') or fname in ['files_json', 'activity_log', 'error_log', 'fiscal_meta_json']:
                        continue
                    
                    file_path = os.path.join(root, fname)
                    
                    # Determine the key name for Firebase
                    # If file is in a subdirectory (excel/, epsilon/), include it in the key
                    # Otherwise, convert extension to suffix (json -> _json, xlsx -> _xlsx)
                    rel_path = os.path.relpath(file_path, source_dir)
                    rel_path = rel_path.replace('\\', '/')  # Normalize paths
                    
                    # If file is in root directory, convert extension to suffix
                    if '/' not in rel_path:
                        # This is a root-level file
                        # Convert: credentials_settings.json -> credentials_settings_json
                        name_no_ext = os.path.splitext(fname)[0]
                        ext = os.path.splitext(fname)[1]
                        
                        # Map extensions to suffixes
                        ext_map = {
                            '.json': '_json',
                            '.xlsx': '_xlsx',
                            '.xls': '_xls',
                            '.pdf': '_pdf',
                            '.csv': '_csv',
                            '.txt': '_txt',
                            '.xml': '_xml',
                        }
                        
                        suffix = ext_map.get(ext.lower(), f'_{ext.lower().lstrip(".")}')
                        firebase_key = f"{name_no_ext}{suffix}"
                    else:
                        # File is in a subdirectory (excel/, epsilon/)
                        # Keep the path as-is
                        firebase_key = rel_path
                    
                    local_file_keys.add(firebase_key)
                    
                    # Read file
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
                    
                    # Encrypt
                    encrypted_content = cipher.encrypt(file_content)
                    logger.debug('[PUSH] Encrypted file %s (size: %d -> %d)', firebase_key, len(file_content), len(encrypted_content))
                    
                    # Base64 encode
                    content_b64 = base64.urlsafe_b64encode(encrypted_content).decode('utf-8')
                    
                    # Get mtime
                    mtime = os.path.getmtime(file_path)
                    
                    # Prepare file payload
                    file_payload = {
                        'content': content_b64,
                        '_meta': {
                            'mtime': mtime,
                            'size': len(file_content)
                        }
                    }
                    
                    # Upload to Firebase
                    firebase_path = f'/groups/{group_name}/files/{firebase_key}'
                    if firebase_write_data(firebase_path, file_payload):
                        logger.info('[PUSH] Uploaded file to Firebase: %s', firebase_key)
                        files_uploaded += 1
                    else:
                        files_failed += 1
                        logger.error('[PUSH] Failed to upload file to Firebase: %s', firebase_key)
                
                except Exception as e:
                    files_failed += 1
                    logger.error('[PUSH] Error processing file %s: %s', fname, e)
        
        # Now detect and remove deleted files from Firebase
        try:
            firebase_path = f'/groups/{group_name}/files'
            remote_files = firebase_read_data_compressed(firebase_path) or {}
            
            if isinstance(remote_files, dict):
                def _find_all_keys(obj, prefix=''):
                    """Recursively find all keys that look like files (have content + _meta)"""
                    result = set()
                    if not isinstance(obj, dict):
                        return result
                    for key, val in obj.items():
                        key_str = str(key).lstrip('/')
                        current_path = f"{prefix}/{key_str}".lstrip('/')
                        if isinstance(val, dict) and 'content' in val and '_meta' in val:
                            result.add(current_path)
                        elif isinstance(val, dict):
                            result.update(_find_all_keys(val, current_path))
                    return result
                
                remote_file_keys = _find_all_keys(remote_files)
                
                # Find keys that exist in Firebase but not locally
                deleted_keys = remote_file_keys - local_file_keys
                
                for deleted_key in deleted_keys:
                    try:
                        delete_path = f'/groups/{group_name}/files/{deleted_key}'
                        if firebase_write_data(delete_path, None):  # Writing None deletes the key
                            logger.info('[PUSH] Deleted file from Firebase: %s', deleted_key)
                            files_deleted += 1
                        else:
                            logger.warning('[PUSH] Failed to delete file from Firebase: %s', deleted_key)
                    except Exception as e:
                        logger.error('[PUSH] Error deleting file from Firebase %s: %s', deleted_key, e)
        
        except Exception as e:
            logger.warning('[PUSH] Could not detect deleted files: %s', e)
        
        # Log summary
        logger.info('[PUSH] Pushed files for group %s: uploaded %d files, deleted %d files, %d failed', 
                    group_name, files_uploaded, files_deleted, files_failed)
        
        return True
    
    except Exception as e:
        logger.error('[PUSH] Failed to push files for group %s: %s', group_name, e)
        return False


def firebase_pull_group_to_local(group_name: str, local_data_root: str = None) -> bool:
    """Download group data from Firebase and populate `data/<group_name>` locally.

    This is a best-effort lazy-sync used when server is missing a group's data.
    Only files from the 'files' folder in Firebase are pulled and stored locally.
    All files are flattened directly into the group's folder (no nested structure).
    It will:
    1. Read only data from /groups/{group_name}/files
    2. Recursively find all files (content + _meta pairs)
    3. Decrypt encrypted files using Fernet key
    4. Store all files directly in data/<group_name>/ (flattened)
    5. Log all actions for admin visibility
    
    Returns True if pull succeeded (or no data found to pull).
    """
    try:
        if not is_firebase_enabled():
            logger.warning('Firebase not enabled; cannot pull group data')
            return False

        if local_data_root is None:
            local_data_root = os.path.join(os.getcwd(), 'data')

        # Read only from the 'files' subfolder in Firebase
        path = f'/groups/{group_name}/files'
        exported = firebase_read_data_compressed(path) or {}
        if not isinstance(exported, dict):
            logger.warning('No files found in Firebase for %s at path %s', group_name, path)
            return True

        target_dir = os.path.join(local_data_root, group_name)
        os.makedirs(target_dir, exist_ok=True)

        files_created = 0
        files_failed = 0
        
        # Get encryption key once
        fernet_key = encryption._ensure_key()
        if not fernet_key:
            logger.warning('[PULL] No Fernet key available; encrypted files will not be decrypted')
        
        def _get_file_name_with_extension(key_name):
            """
            Convert key name to proper file name with extension.
            E.g., 'credentials_settings_json' -> 'credentials_settings.json'
                  '12345679_2024_invoices_xlsx' -> '12345679_2024_invoices.xlsx'
            """
            key_str = str(key_name).lstrip('/')
            
            # Map of suffixes to extensions
            extension_map = {
                '_json': '.json',
                '_xlsx': '.xlsx',
                '_xls': '.xls',
                '_pdf': '.pdf',
                '_csv': '.csv',
                '_txt': '.txt',
                '_xml': '.xml',
            }
            
            # Check for known extensions at the end
            for suffix, ext in extension_map.items():
                if key_str.endswith(suffix):
                    # Replace the suffix with the extension
                    base_name = key_str[:-len(suffix)]
                    return f"{base_name}{ext}"
            
            # If no extension found, return as-is
            return key_str
        
        def _recursive_process(obj):
            """Recursively find all files (flattened) and materialize them"""
            nonlocal files_created, files_failed
            
            if not isinstance(obj, dict):
                return
            
            for key, val in obj.items():
                try:
                    # Check if this is a binary file (has content + _meta)
                    if isinstance(val, dict) and 'content' in val and '_meta' in val:
                        # This is a file - materialize it directly in target_dir
                        try:
                            # Get proper file name with extension
                            file_name = _get_file_name_with_extension(key)
                            content_b64 = val.get('content')
                            logger.debug('[PULL] Processing file: %s (original key: %s)', file_name, key)
                            
                            # Base64 decode
                            blob = base64.urlsafe_b64decode(content_b64.encode('utf-8'))
                            logger.debug('[PULL] Decoded %d bytes for %s', len(blob), file_name)
                            
                            # Try to decrypt if key is available
                            decrypted = False
                            if fernet_key:
                                from cryptography.fernet import Fernet
                                try:
                                    cipher = Fernet(fernet_key)

                                    blob = cipher.decrypt(blob)
                                    decrypted = True
                                    logger.info('[PULL] Decrypted file: %s (size: %d bytes)', file_name, len(blob))
                                except Exception as de:
                                    logger.warning('[PULL] Decrypt failed for %s: %s (using as-is)', file_name, de)
                            else:
                                logger.warning('[PULL] No key available; skipping decrypt for %s', file_name)
                            
                            # Determine target subdirectory based on file type
                            file_dir = target_dir
                            
                            # Route .xlsx files to excel/ subdirectory
                            if file_name.endswith('.xlsx'):
                                file_dir = os.path.join(target_dir, 'excel')
                                os.makedirs(file_dir, exist_ok=True)
                                logger.debug('[PULL] Routing .xlsx file to excel/ subdirectory: %s', file_name)
                            
                            # Route epsilon_invoices files to epsilon/ subdirectory
                            elif 'epsilon_invoices' in file_name:
                                file_dir = os.path.join(target_dir, 'epsilon')
                                os.makedirs(file_dir, exist_ok=True)
                                logger.debug('[PULL] Routing epsilon_invoices file to epsilon/ subdirectory: %s', file_name)
                            
                            # Write file to appropriate directory
                            target_file_path = os.path.join(file_dir, file_name)
                            with open(target_file_path, 'wb') as fh:
                                fh.write(blob)
                            logger.info('[PULL] Wrote file %s to %s (size: %d bytes, decrypted: %s)', 
                                       file_name, file_dir, len(blob), decrypted)
                            
                            # Set mtime if available
                            try:
                                mtime = float(val.get('_meta', {}).get('mtime', 0))
                                if mtime:
                                    os.utime(target_file_path, (mtime, mtime))
                            except Exception:
                                pass
                            
                            files_created += 1
                        except Exception as e:
                            files_failed += 1
                            logger.error('[PULL] Failed to materialize file %s: %s', key, e)
                    
                    elif isinstance(val, dict):
                        # This is a nested dict - recurse into it to find files
                        logger.debug('[PULL] Recursing into nested dict at key: %s', key)
                        _recursive_process(val)
                    
                    else:
                        # Other types - skip
                        logger.debug('[PULL] Skipping non-dict value at key %s', key)
                
                except Exception as e:
                    files_failed += 1
                    logger.error('[PULL] Error processing key %s: %s', key, e)
        
        # Start recursive processing
        _recursive_process(exported)

        # Log summary
        logger.info('[PULL] Pulled files for group %s: created %d files, %d failed. Stored in: %s', 
                    group_name, files_created, files_failed, target_dir)
        
        return True
    
    except Exception as e:
        logger.error('Failed to pull files for group %s: %s', group_name, e)
        return False


def ensure_group_data_local(group_folder: str, create_empty_dirs: bool = True) -> bool:
    """
    Ensure a group's data folder exists locally.
    
    Strategy:
    1. If folder already exists locally, return True immediately (fast path)
    2. If missing, attempt lazy-pull from Firebase
    3. If Firebase pull fails/empty, optionally create empty folder structure
    
    This is the primary entry point for lazy-loading group data.
    Used by routes to ensure data is available before processing.
    
    Args:
        group_folder: The data_folder name (e.g., 'client_xyz')
        create_empty_dirs: If True, create empty folder even if Firebase has no data
    
    Returns:
        True if folder now exists and is accessible (or will be created)
        False only if there's a critical error
    """
    try:
        if not group_folder:
            logger.warning('ensure_group_data_local: No group_folder provided')
            return False
        
        data_root = os.path.join(os.getcwd(), 'data')
        target_dir = os.path.join(data_root, group_folder)
        
        # Fast path: folder already exists
        if os.path.isdir(target_dir):
            logger.debug('Group data already exists locally: %s', group_folder)
            return True
        
        # Attempt to pull from Firebase
        logger.info('Group data missing locally, attempting lazy-pull: %s', group_folder)
        if firebase_pull_group_to_local(group_folder, data_root):
            # Pull succeeded (either found data or returned without error)
            # Ensure the folder exists (might be empty if Firebase had no data)
            if create_empty_dirs:
                os.makedirs(target_dir, exist_ok=True)
                # Also create common subdirectories proactively
                for subdir in ['epsilon', 'excel', '__pycache__']:
                    try:
                        os.makedirs(os.path.join(target_dir, subdir), exist_ok=True)
                    except Exception:
                        pass
            logger.info('Successfully ensured group data local: %s', group_folder)
            return True
        
        # Pull failed, but if create_empty_dirs is True, create folder anyway
        if create_empty_dirs:
            try:
                os.makedirs(target_dir, exist_ok=True)
                # Create common subdirectories
                for subdir in ['epsilon', 'excel']:
                    os.makedirs(os.path.join(target_dir, subdir), exist_ok=True)
                logger.warning('Created empty group folder (Firebase pull failed): %s', group_folder)
                return True
            except Exception as e:
                logger.error('Failed to create empty group folder: %s (error: %s)', group_folder, e)
                return False
        
        logger.warning('Could not ensure group data local and create_empty_dirs=False: %s', group_folder)
        return False
    
    except Exception as e:
        logger.error('Unexpected error in ensure_group_data_local for %s: %s', group_folder, e)
        return False


def firebase_import_group_data(group_name: str, data: Dict[str, Any]) -> bool:
    """Import data for a group to Firebase"""
    try:
        if not is_firebase_enabled():
            return False
        
        path = f'/groups/{group_name}'
        # Use compressed write to reduce payload size when appropriate
        return firebase_write_compressed(path, data)
    except Exception as e:
        logger.error(f"Failed to import group data for {group_name}: {e}")
        return False


# ============================================================================
# File sync helpers
# ============================================================================

_sync_thread = None
_sync_stop = False
_sync_state_path = os.path.join(os.getcwd(), 'data', '.firebase_sync_state.json')

# Map user_id -> last db write timestamp (epoch seconds)
_user_last_db_activity = {}
# Map user_id -> threading.Timer so we can cancel / reschedule idle syncs
_user_idle_timers = {}

# Idle timeout in seconds (10 minutes default). Can be adjusted by tests/env.
IDLE_SYNC_TIMEOUT = int(os.getenv('FIREBASE_IDLE_SYNC_TIMEOUT', '600'))


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


def firebase_sync_group_folder(group_folder: str, data_dir: str = None) -> bool:
    """Perform immediate sync of a single group folder under `data/`.

    `group_folder` must be the filesystem folder name under `data/` (this is the
    Group.data_folder value). Returns True if the sync ran without fatal errors.
    """
    try:
        if not is_firebase_enabled():
            logger.warning('Firebase not enabled; skipping group sync')
            return False

        if not group_folder:
            logger.warning('No group folder provided for firebase_sync_group_folder')
            return False

        if data_dir is None:
            data_dir = os.path.join(os.getcwd(), 'data')

        # run a single scan for the specified folder
        _scan_and_sync_data_dir(data_dir, group_names=[group_folder])
        logger.info('Completed firebase_sync_group_folder for %s', group_folder)
        return True
    except Exception as e:
        logger.error('Error syncing group folder to Firebase: %s', e)
        return False


def _user_idle_sync_handler(user_id: int, group_folder: str) -> None:
    """Called by timer when a user has been idle long enough to trigger sync."""
    try:
        last_ts = _user_last_db_activity.get(str(user_id) if isinstance(user_id, str) else user_id)
        if not last_ts:
            logger.debug('Idle sync: no last activity record for user %s', user_id)
            return

        # If current time now is at least IDLE_SYNC_TIMEOUT seconds after last activity, proceed
        if time.time() - float(last_ts) >= IDLE_SYNC_TIMEOUT:
            logger.info('User %s idle for >= %s seconds. Syncing group %s', user_id, IDLE_SYNC_TIMEOUT, group_folder)
            # Perform a targeted group sync
            firebase_sync_group_folder(group_folder)
        else:
            logger.debug('Idle sync: user %s not idle anymore (last %s)', user_id, last_ts)
    except Exception as e:
        logger.error('Error during user idle sync handler for %s: %s', user_id, e)
    finally:
        # cleanup timer reference
        try:
            _user_idle_timers.pop(user_id, None)
        except Exception:
            pass


def firebase_record_db_activity(user_id: int, group_folder: str) -> None:
    """Record that a user performed a DB-write action and (re)schedule idle sync.

    When called, this stores a last-activity timestamp and schedules a Timer
    to call `_user_idle_sync_handler` after `IDLE_SYNC_TIMEOUT` seconds. If the
    user performs more DB writes, the timer is reset.
    """
    try:
        if not user_id:
            return

        # Normalize to str key to be safe across sessions
        key = str(user_id)
        _user_last_db_activity[key] = time.time()

        # Cancel previous timer if exists
        prev = _user_idle_timers.get(key)
        if prev and isinstance(prev, threading.Timer):
            try:
                prev.cancel()
            except Exception:
                pass

        # Only schedule if group_folder is provided
        if not group_folder:
            return

        t = threading.Timer(IDLE_SYNC_TIMEOUT, _user_idle_sync_handler, args=(key, group_folder))
        t.daemon = True
        t.start()
        _user_idle_timers[key] = t
        logger.debug('Scheduled idle sync for user %s (group=%s) in %s seconds', user_id, group_folder, IDLE_SYNC_TIMEOUT)
    except Exception as e:
        logger.error('Failed to schedule idle sync for user %s: %s', user_id, e)


def firebase_cancel_idle_sync_for_user(user_id: int) -> None:
    """Cancel a pending idle sync for a user (used on logout)."""
    key = str(user_id)
    t = _user_idle_timers.pop(key, None)
    try:
        if t and isinstance(t, threading.Timer):
            t.cancel()
    except Exception:
        pass
    _user_last_db_activity.pop(key, None)


def stop_firebase_data_sync() -> None:
    global _sync_stop, _sync_thread
    _sync_stop = True
    if _sync_thread:
        _sync_thread.join(timeout=2)
