"""
Encryption/Decryption utilities for securing group data
"""
import os
import json
import base64
import logging
from typing import Optional, Any, Dict

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# ============================================================================
# Encryption Configuration
# ============================================================================

MASTER_ENCRYPTION_KEY = os.getenv("MASTER_ENCRYPTION_KEY")  # Base64-encoded Fernet key
ENCRYPTION_SALT = os.getenv("ENCRYPTION_SALT", "firebed-default-salt-change-me").encode()


def _ensure_key() -> Optional[bytes]:
    """Ensure we have an encryption key"""
    if MASTER_ENCRYPTION_KEY:
        try:
            return base64.urlsafe_b64decode(MASTER_ENCRYPTION_KEY.encode())
        except Exception as e:
            logger.error(f"Failed to decode MASTER_ENCRYPTION_KEY: {e}")
    return None


def generate_encryption_key() -> str:
    """Generate a new Fernet key (call this once during setup)"""
    key = Fernet.generate_key()
    # Επιστρέφουμε string για να το βάλεις στο env (MASTER_ENCRYPTION_KEY)
    return base64.urlsafe_b64encode(key).decode("utf-8")


def derive_key_from_password(password: str, salt: Optional[bytes] = None) -> bytes:
    """Derive an encryption key from a password using PBKDF2 (PBKDF2HMAC)"""
    if salt is None:
        salt = ENCRYPTION_SALT

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    key = base64.urlsafe_b64encode(
        kdf.derive(password.encode("utf-8"))
    )
    return key


# ============================================================================
# Encryption/Decryption Functions
# ============================================================================

def encrypt_data(data: Dict[str, Any], key: Optional[bytes] = None) -> Optional[str]:
    """
    Encrypt a dictionary to a base64-encoded string
    
    Args:
        data: Dictionary to encrypt
        key: Encryption key (uses MASTER_ENCRYPTION_KEY if not provided)
    
    Returns:
        Encrypted base64 string, or None on failure
    """
    try:
        if key is None:
            key = _ensure_key()
        
        if not key:
            logger.error("No encryption key available")
            return None
        
        cipher = Fernet(key)
        json_str = json.dumps(data, ensure_ascii=False)
        encrypted = cipher.encrypt(json_str.encode('utf-8'))
        return base64.urlsafe_b64encode(encrypted).decode('utf-8')
    
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return None


def decrypt_data(encrypted_str: str, key: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
    """
    Decrypt a base64-encoded string back to a dictionary
    
    Args:
        encrypted_str: Encrypted base64 string
        key: Encryption key (uses MASTER_ENCRYPTION_KEY if not provided)
    
    Returns:
        Decrypted dictionary, or None on failure
    """
    try:
        if key is None:
            key = _ensure_key()
        
        if not key:
            logger.error("No encryption key available")
            return None
        
        cipher = Fernet(key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_str.encode('utf-8'))
        decrypted = cipher.decrypt(encrypted_bytes)
        return json.loads(decrypted.decode('utf-8'))
    
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return None


def encrypt_file(file_path: str, output_path: str, key: Optional[bytes] = None) -> bool:
    """
    Encrypt a file
    
    Args:
        file_path: Path to file to encrypt
        output_path: Path to save encrypted file
        key: Encryption key
    
    Returns:
        True on success, False on failure
    """
    try:
        if key is None:
            key = _ensure_key()
        
        if not key:
            logger.error("No encryption key available")
            return False
        
        with open(file_path, 'rb') as f:
            file_data = f.read()
        
        cipher = Fernet(key)
        encrypted = cipher.encrypt(file_data)
        
        with open(output_path, 'wb') as f:
            f.write(encrypted)
        
        logger.info(f"File encrypted: {file_path} -> {output_path}")
        return True
    
    except Exception as e:
        logger.error(f"File encryption failed: {e}")
        return False


def decrypt_file(encrypted_path: str, output_path: str, key: Optional[bytes] = None) -> bool:
    """
    Decrypt a file
    
    Args:
        encrypted_path: Path to encrypted file
        output_path: Path to save decrypted file
        key: Encryption key
    
    Returns:
        True on success, False on failure
    """
    try:
        if key is None:
            key = _ensure_key()
        
        if not key:
            logger.error("No encryption key available")
            return False
        
        with open(encrypted_path, 'rb') as f:
            encrypted_data = f.read()
        
        cipher = Fernet(key)
        decrypted = cipher.decrypt(encrypted_data)
        
        with open(output_path, 'wb') as f:
            f.write(decrypted)
        
        logger.info(f"File decrypted: {encrypted_path} -> {output_path}")
        return True
    
    except Exception as e:
        logger.error(f"File decryption failed: {e}")
        return False


# ============================================================================
# Group-Specific Encryption (with per-group keys stored in DB)
# ============================================================================

def encrypt_data_with_group_key(data: Dict[str, Any], group_key: Optional[str] = None) -> Optional[str]:
    """
    Encrypt data using a group-specific key (stored in DB or derived from group password)
    
    Args:
        data: Dictionary to encrypt
        group_key: Group encryption key (base64 Fernet key), uses MASTER_ENCRYPTION_KEY if not provided
    
    Returns:
        Encrypted base64 string
    """
    try:
        if group_key:
            try:
                key = base64.urlsafe_b64decode(group_key.encode())
            except Exception:
                logger.error("Invalid group key format")
                return None
        else:
            key = _ensure_key()
        
        return encrypt_data(data, key)
    except Exception as e:
        logger.error(f"Group encryption failed: {e}")
        return None


def decrypt_data_with_group_key(encrypted_str: str, group_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Decrypt data using a group-specific key
    
    Args:
        encrypted_str: Encrypted base64 string
        group_key: Group encryption key (base64 Fernet key)
    
    Returns:
        Decrypted dictionary
    """
    try:
        if group_key:
            try:
                key = base64.urlsafe_b64decode(group_key.encode())
            except Exception:
                logger.error("Invalid group key format")
                return None
        else:
            key = _ensure_key()
        
        return decrypt_data(encrypted_str, key)
    except Exception as e:
        logger.error(f"Group decryption failed: {e}")
        return None


def generate_group_encryption_key() -> str:
    """Generate a new encryption key for a group"""
    return generate_encryption_key()
