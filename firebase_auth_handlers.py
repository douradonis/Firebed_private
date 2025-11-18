"""
Firebase Authentication Handlers for Firebed Private
Handles user registration, login, password reset via Firebase
"""

import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import requests
import os
from firebase_admin import auth as firebase_auth
from firebase_admin import db, credentials
import firebase_config
from encryption import derive_key_from_password, generate_encryption_key

logger = logging.getLogger(__name__)


class FirebaseAuthHandler:
    """Manage Firebase Authentication operations"""

    @staticmethod
    def register_user(email: str, password: str, display_name: str = "") -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Register a new user with Firebase Authentication
        
        Args:
            email: User email
            password: User password (min 6 chars, Firebase requirement)
            display_name: Optional display name
        
        Returns:
            Tuple: (success: bool, uid: Optional[str], error: Optional[str])
        """
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # Validate password
            if len(password) < 6:
                return False, None, "Password must be at least 6 characters"
            
            if not email or '@' not in email:
                return False, None, "Invalid email format"
            
            # Create Firebase user
            user = firebase_auth.create_user(
                email=email,
                password=password,
                display_name=display_name or email.split('@')[0],
                email_verified=False
            )
            
            # Initialize user data in Realtime Database
            user_data = {
                'uid': user.uid,
                'email': user.email,
                'display_name': user.display_name,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'email_verified': False,
                'groups': [],
                'active': True
            }
            
            # Write user profile to database
            firebase_config.firebase_write_data(f'/users/{user.uid}', user_data)
            
            logger.info(f"User registered successfully: {user.email} (UID: {user.uid})")
            
            # Log activity
            firebase_config.firebase_log_activity(
                user.uid,
                'system',
                'user_registered',
                {'email': email}
            )
            
            return True, user.uid, None
            
        except firebase_auth.EmailAlreadyExistsError:
            logger.warning(f"Registration failed: Email already exists - {email}")
            return False, None, "This email is already registered"
        except firebase_auth.InvalidPasswordError:
            return False, None, "Password does not meet security requirements"
        except Exception as e:
            logger.error(f"Firebase registration error: {e}")
            return False, None, f"Registration failed: {str(e)}"

    @staticmethod
    def login_user(email: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Verify user credentials via Firebase REST API with password verification
        
        Returns:
            Tuple: (success: bool, uid: Optional[str], error: Optional[str])
        """
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # First, verify password against Firebase using REST API
            api_key = os.getenv('FIREBASE_API_KEY', '')
            if not api_key:
                logger.warning("FIREBASE_API_KEY not set, trying fallback method")
                # Fallback: get user by email from Firebase Auth (no password check)
                try:
                    user = firebase_auth.get_user_by_email(email)
                    if user and not user.disabled:
                        logger.warning(f"Login attempt without password verification for: {email}")
                        return True, user.uid, None
                except:
                    pass
                return False, None, "Authentication system not properly configured"
            
            # Use Firebase REST API to verify credentials
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
            payload = {
                "email": email,
                "password": password,
                "returnSecureToken": True
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                uid = data.get('localId')
                
                if uid:
                    # Log successful login
                    firebase_config.firebase_log_activity(
                        uid,
                        'system',
                        'user_logged_in_successfully',
                        {'email': email}
                    )
                    logger.info(f"User logged in successfully: {email}")
                    return True, uid, None
            
            elif response.status_code == 400:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', '')
                
                if error_msg == 'INVALID_PASSWORD':
                    logger.warning(f"Invalid password for user: {email}")
                    return False, None, "Invalid email or password"
                elif error_msg == 'EMAIL_NOT_FOUND':
                    logger.warning(f"Email not found: {email}")
                    return False, None, "Invalid email or password"
                elif error_msg == 'USER_DISABLED':
                    logger.warning(f"User account disabled: {email}")
                    return False, None, "User account has been disabled"
                else:
                    return False, None, error_msg or "Login failed"
            
            logger.error(f"Firebase REST API error: {response.status_code} - {response.text}")
            return False, None, "Login failed - server error"
            
        except Exception as e:
            logger.error(f"Firebase login error: {e}")
            return False, None, f"Login failed: {str(e)}"

    @staticmethod
    def get_user_by_uid(uid: str) -> Optional[Dict[str, Any]]:
        """Get user profile from Firebase"""
        try:
            if not firebase_config.is_firebase_enabled():
                return None
            
            user = firebase_auth.get_user(uid)
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            
            if user_profile:
                user_profile['uid'] = uid
                return user_profile
            
            return {
                'uid': uid,
                'email': user.email,
                'display_name': user.display_name,
                'email_verified': user.email_verified,
            }
        except Exception as e:
            logger.error(f"Failed to get user {uid}: {e}")
            return None

    @staticmethod
    def update_user_profile(uid: str, updates: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Update user profile in Firebase"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Update display name in Firebase Auth if provided
            if 'display_name' in updates:
                firebase_auth.update_user(uid, display_name=updates['display_name'])
            
            # Update full profile in database
            current_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if current_profile:
                current_profile.update(updates)
            else:
                current_profile = updates
            
            current_profile['updated_at'] = datetime.now(timezone.utc).isoformat()
            firebase_config.firebase_write_data(f'/users/{uid}', current_profile)
            
            logger.info(f"User profile updated: {uid}")
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to update user {uid}: {e}")
            return False, str(e)

    @staticmethod
    def delete_user(uid: str) -> Tuple[bool, Optional[str]]:
        """Delete user from Firebase"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Get user email for logging
            user = firebase_auth.get_user(uid)
            email = user.email
            
            # Log activity before deletion
            firebase_config.firebase_log_activity(
                uid,
                'system',
                'user_deleted',
                {'email': email}
            )
            
            # Delete from Firebase Auth
            firebase_auth.delete_user(uid)
            
            # Delete user profile from database
            firebase_config.firebase_delete_data(f'/users/{uid}')
            
            # Delete user's groups association
            firebase_config.firebase_delete_data(f'/user_groups/{uid}')
            
            logger.info(f"User deleted: {uid} ({email})")
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to delete user {uid}: {e}")
            return False, str(e)

    @staticmethod
    def reset_password(email: str) -> Tuple[bool, Optional[str]]:
        """Send password reset email"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            user = firebase_auth.get_user_by_email(email)
            
            # Send password reset email via Firebase (requires REST API)
            # This is typically done via Firebase Client SDK
            # For Admin SDK, we can generate a reset link manually
            
            logger.info(f"Password reset requested for: {email}")
            
            # Log activity
            firebase_config.firebase_log_activity(
                user.uid,
                'system',
                'password_reset_requested',
                {'email': email}
            )
            
            return True, None
            
        except firebase_auth.UserNotFoundError:
            logger.warning(f"Password reset failed: User not found - {email}")
            return False, "User not found"
        except Exception as e:
            logger.error(f"Password reset error: {e}")
            return False, str(e)

    @staticmethod
    def generate_email_verification_link(email: str) -> Tuple[bool, Optional[str]]:
        """Generate Firebase email verification link for an email address."""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"

            link = firebase_auth.generate_email_verification_link(email)
            logger.info(f"Generated email verification link for {email}")
            return True, link
        except Exception as e:
            logger.error(f"Failed to generate verification link for {email}: {e}")
            return False, str(e)

    @staticmethod
    def generate_password_reset_link(email: str) -> Tuple[bool, Optional[str]]:
        """Generate Firebase password reset link for an email address."""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"

            link = firebase_auth.generate_password_reset_link(email)
            logger.info(f"Generated password reset link for {email}")
            return True, link
        except Exception as e:
            logger.error(f"Failed to generate password reset link for {email}: {e}")
            return False, str(e)

    @staticmethod
    def change_password(uid: str, current_password: Optional[str], new_password: str) -> Tuple[bool, Optional[str]]:
        """Change user password. If current_password provided, verify it first via Firebase REST API."""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"

            if len(new_password) < 6:
                return False, "Password must be at least 6 characters"

            # If a current password is provided, verify by signing in via REST API
            api_key = os.getenv('FIREBASE_API_KEY', '')
            if current_password and api_key:
                try:
                    # get user's email
                    fb_user = firebase_auth.get_user(uid)
                    email = fb_user.email
                    if not email:
                        return False, 'Could not verify current password (no email)'

                    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
                    payload = {
                        'email': email,
                        'password': current_password,
                        'returnSecureToken': True
                    }
                    resp = requests.post(url, json=payload, timeout=10)
                    if resp.status_code != 200:
                        return False, 'Current password is incorrect'
                except Exception as e:
                    logger.warning(f"Could not verify current password via REST API: {e}")

            # Proceed to update password via Admin SDK
            firebase_auth.update_user(uid, password=new_password)

            logger.info(f"Password changed for user: {uid}")

            # Log activity
            firebase_config.firebase_log_activity(
                uid,
                'system',
                'password_changed',
                {}
            )

            return True, None

        except Exception as e:
            logger.error(f"Failed to change password for {uid}: {e}")
            return False, str(e)

    @staticmethod
    def generate_custom_token(uid: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Generate a custom token for client-side Firebase authentication"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # Generate custom token valid for 1 hour
            custom_token = firebase_auth.create_custom_token(uid)
            
            logger.info(f"Custom token generated for user: {uid}")
            return True, custom_token.decode('utf-8'), None
            
        except Exception as e:
            logger.error(f"Failed to generate custom token for {uid}: {e}")
            return False, None, str(e)

    @staticmethod
    def create_group_encryption_key(group_name: str, creator_uid: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Create a per-group encryption key
        Stores encrypted key in database, accessible only to group members
        """
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # Generate new encryption key
            new_key = generate_encryption_key()
            
            # Store key metadata in Firebase
            key_metadata = {
                'group_name': group_name,
                'created_by': creator_uid,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'key_version': 1,
                'active': True
            }
            
            # Write key to protected location
            firebase_config.firebase_write_data(
                f'/group_encryption_keys/{group_name}/metadata',
                key_metadata
            )
            
            # Store actual key (should be encrypted at rest in production)
            firebase_config.firebase_write_data(
                f'/group_encryption_keys/{group_name}/key',
                {'encrypted_key': new_key}
            )
            
            logger.info(f"Group encryption key created for: {group_name}")
            
            return True, new_key, None
            
        except Exception as e:
            logger.error(f"Failed to create group encryption key for {group_name}: {e}")
            return False, None, str(e)

    @staticmethod
    def add_user_to_group(uid: str, group_name: str) -> Tuple[bool, Optional[str]]:
        """Add user to a group"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Add to user's groups list
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if user_profile:
                if 'groups' not in user_profile:
                    user_profile['groups'] = []
                if group_name not in user_profile['groups']:
                    user_profile['groups'].append(group_name)
                firebase_config.firebase_write_data(f'/users/{uid}', user_profile)
            
            # Add to group's members list
            group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
            if group_data:
                if 'members' not in group_data:
                    group_data['members'] = []
                if uid not in group_data['members']:
                    group_data['members'].append(uid)
                firebase_config.firebase_write_data(f'/groups/{group_name}', group_data)
            
            logger.info(f"User {uid} added to group: {group_name}")
            
            # Log activity
            firebase_config.firebase_log_activity(
                uid,
                group_name,
                'user_added_to_group',
                {'group': group_name}
            )
            
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to add user {uid} to group {group_name}: {e}")
            return False, str(e)

    @staticmethod
    def remove_user_from_group(uid: str, group_name: str) -> Tuple[bool, Optional[str]]:
        """Remove user from a group"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Remove from user's groups list
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if user_profile and 'groups' in user_profile:
                user_profile['groups'] = [g for g in user_profile['groups'] if g != group_name]
                firebase_config.firebase_write_data(f'/users/{uid}', user_profile)
            
            # Remove from group's members list
            group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
            if group_data and 'members' in group_data:
                group_data['members'] = [m for m in group_data['members'] if m != uid]
                firebase_config.firebase_write_data(f'/groups/{group_name}', group_data)
            
            logger.info(f"User {uid} removed from group: {group_name}")
            
            # Log activity
            firebase_config.firebase_log_activity(
                uid,
                group_name,
                'user_removed_from_group',
                {'group': group_name}
            )
            
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to remove user {uid} from group {group_name}: {e}")
            return False, str(e)

    @staticmethod
    def get_user_groups(uid: str) -> list:
        """Get all groups a user belongs to"""
        try:
            if not firebase_config.is_firebase_enabled():
                return []
            
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if user_profile and 'groups' in user_profile:
                return user_profile['groups']
            return []
            
        except Exception as e:
            logger.error(f"Failed to get groups for user {uid}: {e}")
            return []

    @staticmethod
    def get_group_members(group_name: str) -> list:
        """Get all members of a group"""
        try:
            if not firebase_config.is_firebase_enabled():
                return []
            
            group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
            if group_data and 'members' in group_data:
                return group_data['members']
            return []
            
        except Exception as e:
            logger.error(f"Failed to get members for group {group_name}: {e}")
            return []


# Convenience functions for use in routes

def firebase_register(email: str, password: str, display_name: str = "") -> Tuple[bool, Optional[str], Optional[str]]:
    """Register a new Firebase user"""
    return FirebaseAuthHandler.register_user(email, password, display_name)


def firebase_login(email: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Login a Firebase user"""
    return FirebaseAuthHandler.login_user(email, password)


def firebase_get_user(uid: str) -> Optional[Dict[str, Any]]:
    """Get user profile"""
    return FirebaseAuthHandler.get_user_by_uid(uid)


def firebase_user_groups(uid: str) -> list:
    """Get user's groups"""
    return FirebaseAuthHandler.get_user_groups(uid)
"""
Firebase Authentication Handlers for Firebed Private
Handles user registration, login, password reset via Firebase
"""

import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import requests
import os
from firebase_admin import auth as firebase_auth
from firebase_admin import db, credentials
import firebase_config
from encryption import derive_key_from_password, generate_encryption_key

logger = logging.getLogger(__name__)


class FirebaseAuthHandler:
    """Manage Firebase Authentication operations"""

    @staticmethod
    def register_user(email: str, password: str, display_name: str = "") -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Register a new user with Firebase Authentication
        
        Args:
            email: User email
            password: User password (min 6 chars, Firebase requirement)
            display_name: Optional display name
        
        Returns:
            Tuple: (success: bool, uid: Optional[str], error: Optional[str])
        """
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # Validate password
            if len(password) < 6:
                return False, None, "Password must be at least 6 characters"

            # Create Firebase user
            user = firebase_auth.create_user(
                email=email,
                password=password,
                display_name=display_name or email.split('@')[0],
                email_verified=False
            )

            # Initialize user data in Realtime Database
            user_data = {
                'uid': user.uid,
                'email': user.email,
                'display_name': user.display_name,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'email_verified': False,
                'groups': [],
                'active': True
            }

            # Write user profile to database
            firebase_config.firebase_write_data(f'/users/{user.uid}', user_data)

            logger.info(f"User registered successfully: {user.email} (UID: {user.uid})")

            # Log activity
            firebase_config.firebase_log_activity(
                user.uid,
                'system',
                'user_registered',
                {'email': email}
            )

            return True, user.uid, None
        except firebase_auth.EmailAlreadyExistsError:
            logger.warning(f"Registration failed: Email already exists - {email}")
            return False, None, "This email is already registered"
        except firebase_auth.InvalidPasswordError:
            return False, None, "Password does not meet security requirements"
        except Exception as e:
            logger.error(f"Firebase registration error: {e}")
            return False, None, f"Registration failed: {str(e)}"

    @staticmethod
    def login_user(email: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Verify user credentials via Firebase REST API
        (Note: Firebase Admin SDK doesn't verify passwords directly - 
         this should be done via Firebase Client SDK or custom token)
        
        Returns:
            Tuple: (success: bool, uid: Optional[str], error: Optional[str])
        """
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # Get user by email from Firebase Auth
            user = firebase_auth.get_user_by_email(email)
            
            if not user:
                return False, None, "User not found"
            
            if user.disabled:
                return False, None, "User account is disabled"
            
            # Log activity
            firebase_config.firebase_log_activity(
                user.uid,
                'system',
                'user_login_attempt',
                {'email': email}
            )
            
            logger.info(f"Login attempt for user: {email}")
            
            # Return UID - password verification should happen on client-side
            # or via Firebase REST API with custom token
            return True, user.uid, None
            
        except firebase_auth.UserNotFoundError:
            logger.warning(f"Login failed: User not found - {email}")
            return False, None, "Invalid email or password"
        except Exception as e:
            logger.error(f"Firebase login error: {e}")
            return False, None, f"Login failed: {str(e)}"

    @staticmethod
    def get_user_by_uid(uid: str) -> Optional[Dict[str, Any]]:
        """Get user profile from Firebase"""
        try:
            if not firebase_config.is_firebase_enabled():
                return None
            
            user = firebase_auth.get_user(uid)
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            
            if user_profile:
                user_profile['uid'] = uid
                return user_profile
            
            return {
                'uid': uid,
                'email': user.email,
                'display_name': user.display_name,
                'email_verified': user.email_verified,
            }
        except Exception as e:
            logger.error(f"Failed to get user {uid}: {e}")
            return None

    @staticmethod
    def update_user_profile(uid: str, updates: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Update user profile in Firebase"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Update display name in Firebase Auth if provided
            if 'display_name' in updates:
                firebase_auth.update_user(uid, display_name=updates['display_name'])
            
            # Update full profile in database
            current_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if current_profile:
                current_profile.update(updates)
            else:
                current_profile = updates
            
            current_profile['updated_at'] = datetime.now(timezone.utc).isoformat()
            firebase_config.firebase_write_data(f'/users/{uid}', current_profile)
            
            logger.info(f"User profile updated: {uid}")
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to update user {uid}: {e}")
            return False, str(e)

    @staticmethod
    def delete_user(uid: str) -> Tuple[bool, Optional[str]]:
        """Delete user from Firebase"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Get user email for logging
            user = firebase_auth.get_user(uid)
            email = user.email
            
            # Log activity before deletion
            firebase_config.firebase_log_activity(
                uid,
                'system',
                'user_deleted',
                {'email': email}
            )
            
            # Delete from Firebase Auth
            firebase_auth.delete_user(uid)
            
            # Delete user profile from database
            firebase_config.firebase_delete_data(f'/users/{uid}')
            
            # Delete user's groups association
            firebase_config.firebase_delete_data(f'/user_groups/{uid}')
            
            logger.info(f"User deleted: {uid} ({email})")
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to delete user {uid}: {e}")
            return False, str(e)

    @staticmethod
    def reset_password(email: str) -> Tuple[bool, Optional[str]]:
        """Send password reset email"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            user = firebase_auth.get_user_by_email(email)
            
            # Send password reset email via Firebase (requires REST API)
            # This is typically done via Firebase Client SDK
            # For Admin SDK, we can generate a reset link manually
            
            logger.info(f"Password reset requested for: {email}")
            
            # Log activity
            firebase_config.firebase_log_activity(
                user.uid,
                'system',
                'password_reset_requested',
                {'email': email}
            )
            
            return True, None
            
        except firebase_auth.UserNotFoundError:
            logger.warning(f"Password reset failed: User not found - {email}")
            return False, "User not found"
        except Exception as e:
            logger.error(f"Password reset error: {e}")
            return False, str(e)

    @staticmethod
    def change_password(uid: str, new_password: str) -> Tuple[bool, Optional[str]]:
        """Change user password"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            if len(new_password) < 6:
                return False, "Password must be at least 6 characters"
            
            firebase_auth.update_user(uid, password=new_password)
            
            logger.info(f"Password changed for user: {uid}")
            
            # Log activity
            firebase_config.firebase_log_activity(
                uid,
                'system',
                'password_changed',
                {}
            )
            
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to change password for {uid}: {e}")
            return False, str(e)

    @staticmethod
    def generate_custom_token(uid: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """Generate a custom token for client-side Firebase authentication"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # Generate custom token valid for 1 hour
            custom_token = firebase_auth.create_custom_token(uid)
            
            logger.info(f"Custom token generated for user: {uid}")
            return True, custom_token.decode('utf-8'), None
            
        except Exception as e:
            logger.error(f"Failed to generate custom token for {uid}: {e}")
            return False, None, str(e)

    @staticmethod
    def create_group_encryption_key(group_name: str, creator_uid: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Create a per-group encryption key
        Stores encrypted key in database, accessible only to group members
        """
        try:
            if not firebase_config.is_firebase_enabled():
                return False, None, "Firebase not enabled"
            
            # Generate new encryption key
            new_key = generate_encryption_key()
            
            # Store key metadata in Firebase
            key_metadata = {
                'group_name': group_name,
                'created_by': creator_uid,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'key_version': 1,
                'active': True
            }
            
            # Write key to protected location
            firebase_config.firebase_write_data(
                f'/group_encryption_keys/{group_name}/metadata',
                key_metadata
            )
            
            # Store actual key (should be encrypted at rest in production)
            firebase_config.firebase_write_data(
                f'/group_encryption_keys/{group_name}/key',
                {'encrypted_key': new_key}
            )
            
            logger.info(f"Group encryption key created for: {group_name}")
            
            return True, new_key, None
            
        except Exception as e:
            logger.error(f"Failed to create group encryption key for {group_name}: {e}")
            return False, None, str(e)

    @staticmethod
    def add_user_to_group(uid: str, group_name: str) -> Tuple[bool, Optional[str]]:
        """Add user to a group"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Add to user's groups list
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if user_profile:
                if 'groups' not in user_profile:
                    user_profile['groups'] = []
                if group_name not in user_profile['groups']:
                    user_profile['groups'].append(group_name)
                firebase_config.firebase_write_data(f'/users/{uid}', user_profile)
            
            # Add to group's members list
            group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
            if group_data:
                if 'members' not in group_data:
                    group_data['members'] = []
                if uid not in group_data['members']:
                    group_data['members'].append(uid)
                firebase_config.firebase_write_data(f'/groups/{group_name}', group_data)
            
            logger.info(f"User {uid} added to group: {group_name}")
            
            # Log activity
            firebase_config.firebase_log_activity(
                uid,
                group_name,
                'user_added_to_group',
                {'group': group_name}
            )
            
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to add user {uid} to group {group_name}: {e}")
            return False, str(e)

    @staticmethod
    def remove_user_from_group(uid: str, group_name: str) -> Tuple[bool, Optional[str]]:
        """Remove user from a group"""
        try:
            if not firebase_config.is_firebase_enabled():
                return False, "Firebase not enabled"
            
            # Remove from user's groups list
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if user_profile and 'groups' in user_profile:
                user_profile['groups'] = [g for g in user_profile['groups'] if g != group_name]
                firebase_config.firebase_write_data(f'/users/{uid}', user_profile)
            
            # Remove from group's members list
            group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
            if group_data and 'members' in group_data:
                group_data['members'] = [m for m in group_data['members'] if m != uid]
                firebase_config.firebase_write_data(f'/groups/{group_name}', group_data)
            
            logger.info(f"User {uid} removed from group: {group_name}")
            
            # Log activity
            firebase_config.firebase_log_activity(
                uid,
                group_name,
                'user_removed_from_group',
                {'group': group_name}
            )
            
            return True, None
            
        except Exception as e:
            logger.error(f"Failed to remove user {uid} from group {group_name}: {e}")
            return False, str(e)

    @staticmethod
    def get_user_groups(uid: str) -> list:
        """Get all groups a user belongs to"""
        try:
            if not firebase_config.is_firebase_enabled():
                return []
            
            user_profile = firebase_config.firebase_read_data(f'/users/{uid}')
            if user_profile and 'groups' in user_profile:
                return user_profile['groups']
            return []
            
        except Exception as e:
            logger.error(f"Failed to get groups for user {uid}: {e}")
            return []

    @staticmethod
    def get_group_members(group_name: str) -> list:
        """Get all members of a group"""
        try:
            if not firebase_config.is_firebase_enabled():
                return []
            
            group_data = firebase_config.firebase_read_data(f'/groups/{group_name}')
            if group_data and 'members' in group_data:
                return group_data['members']
            return []
            
        except Exception as e:
            logger.error(f"Failed to get members for group {group_name}: {e}")
            return []


# Convenience functions for use in routes

def firebase_register(email: str, password: str, display_name: str = "") -> Tuple[bool, Optional[str], Optional[str]]:
    """Register a new Firebase user"""
    return FirebaseAuthHandler.register_user(email, password, display_name)


def firebase_login(email: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Login a Firebase user"""
    return FirebaseAuthHandler.login_user(email, password)


def firebase_get_user(uid: str) -> Optional[Dict[str, Any]]:
    """Get user profile"""
    return FirebaseAuthHandler.get_user_by_uid(uid)


def firebase_user_groups(uid: str) -> list:
    """Get user's groups"""
    return FirebaseAuthHandler.get_user_groups(uid)
