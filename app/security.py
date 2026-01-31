"""
Security Module for RAG System.

Provides:
- Encrypted storage for sensitive data (index, manifest)
- macOS Keychain integration for API keys
- Audit logging for file access
- Secure key management
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import pickle
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger("rag.security")

# Try to import keyring for macOS Keychain
try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    logger.info("keyring not installed - using .env fallback for API keys")


# ============================================================================
# Key Management
# ============================================================================

class KeyManager:
    """
    Manages encryption keys and API credentials securely.
    
    Supports:
    - macOS Keychain (via keyring) for API keys
    - Derived encryption keys for index storage
    - Fallback to .env for systems without keychain
    """
    
    SERVICE_NAME = "RAG-Personal-Search"
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._salt_path = data_dir / ".salt"
        self._key_cache: dict[str, bytes] = {}
    
    # ---- API Key Management ----
    
    def get_api_key(self, key_name: str = "OPENAI_API_KEY") -> str | None:
        """
        Retrieve API key from keychain or environment.
        
        Priority:
        1. macOS Keychain (if available)
        2. Environment variable
        3. .env file (loaded by python-dotenv)
        """
        # Try keychain first
        if KEYRING_AVAILABLE:
            try:
                key = keyring.get_password(self.SERVICE_NAME, key_name)
                if key:
                    return key.strip()
            except Exception as e:
                logger.debug("Keychain access failed: %s", e)
        
        # Fall back to environment
        key = os.getenv(key_name)
        return key.strip() if key else None
    
    def set_api_key(self, key_name: str, key_value: str) -> bool:
        """
        Store API key in keychain (if available).
        
        Returns True if stored in keychain, False if only available via env.
        """
        if not KEYRING_AVAILABLE:
            logger.warning("Keychain not available. Set %s in .env file.", key_name)
            return False
        
        try:
            keyring.set_password(self.SERVICE_NAME, key_name, key_value.strip())
            logger.info("API key stored in keychain: %s", key_name)
            return True
        except Exception as e:
            logger.error("Failed to store in keychain: %s", e)
            return False
    
    def delete_api_key(self, key_name: str) -> bool:
        """Remove API key from keychain."""
        if not KEYRING_AVAILABLE:
            return False
        
        try:
            keyring.delete_password(self.SERVICE_NAME, key_name)
            return True
        except Exception:
            return False
    
    # ---- Encryption Key Management ----
    
    def _get_or_create_salt(self) -> bytes:
        """Get or create a salt for key derivation."""
        if self._salt_path.exists():
            return self._salt_path.read_bytes()
        
        salt = secrets.token_bytes(32)
        self._salt_path.parent.mkdir(parents=True, exist_ok=True)
        self._salt_path.write_bytes(salt)
        return salt
    
    def derive_key(self, purpose: str = "index") -> bytes:
        """
        Derive an encryption key for a specific purpose.
        
        Uses PBKDF2 with a machine-specific seed.
        """
        if purpose in self._key_cache:
            return self._key_cache[purpose]
        
        # Create machine-specific seed
        machine_id = self._get_machine_id()
        salt = self._get_or_create_salt()
        
        # Derive key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,  # OWASP recommended minimum
        )
        
        seed = f"{machine_id}:{purpose}".encode()
        key = base64.urlsafe_b64encode(kdf.derive(seed))
        
        self._key_cache[purpose] = key
        return key
    
    def _get_machine_id(self) -> str:
        """Get a machine-specific identifier."""
        # Use a combination of factors for machine identification
        factors = [
            os.getenv("USER", ""),
            str(Path.home()),
            os.uname().nodename if hasattr(os, "uname") else "",
        ]
        combined = ":".join(factors).encode()
        return hashlib.sha256(combined).hexdigest()[:32]


# ============================================================================
# Encrypted Storage
# ============================================================================

class EncryptedStorage:
    """
    Provides encrypted read/write for sensitive data.
    
    Uses Fernet (AES-128-CBC) symmetric encryption.
    """
    
    def __init__(self, key_manager: KeyManager):
        self.key_manager = key_manager
        self._fernet_cache: dict[str, Fernet] = {}
    
    def _get_fernet(self, purpose: str) -> Fernet:
        """Get or create Fernet instance for a purpose."""
        if purpose not in self._fernet_cache:
            key = self.key_manager.derive_key(purpose)
            self._fernet_cache[purpose] = Fernet(key)
        return self._fernet_cache[purpose]
    
    def encrypt_data(self, data: bytes, purpose: str = "index") -> bytes:
        """Encrypt raw bytes."""
        fernet = self._get_fernet(purpose)
        return fernet.encrypt(data)
    
    def decrypt_data(self, encrypted: bytes, purpose: str = "index") -> bytes:
        """Decrypt raw bytes."""
        fernet = self._get_fernet(purpose)
        return fernet.decrypt(encrypted)
    
    def save_encrypted_pickle(
        self,
        data: Any,
        path: Path,
        purpose: str = "index"
    ) -> None:
        """Save Python object as encrypted pickle."""
        raw = pickle.dumps(data)
        encrypted = self.encrypt_data(raw, purpose)
        path.write_bytes(encrypted)
    
    def load_encrypted_pickle(
        self,
        path: Path,
        purpose: str = "index"
    ) -> Any:
        """Load Python object from encrypted pickle."""
        encrypted = path.read_bytes()
        raw = self.decrypt_data(encrypted, purpose)
        return pickle.loads(raw)
    
    def save_encrypted_json(
        self,
        data: dict,
        path: Path,
        purpose: str = "manifest"
    ) -> None:
        """Save JSON data encrypted."""
        raw = json.dumps(data, indent=2).encode("utf-8")
        encrypted = self.encrypt_data(raw, purpose)
        path.write_bytes(encrypted)
    
    def load_encrypted_json(
        self,
        path: Path,
        purpose: str = "manifest"
    ) -> dict:
        """Load encrypted JSON data."""
        encrypted = path.read_bytes()
        raw = self.decrypt_data(encrypted, purpose)
        return json.loads(raw.decode("utf-8"))


# ============================================================================
# Audit Logging
# ============================================================================

class AuditLogger:
    """
    Audit logger for tracking file access and indexing operations.
    
    Maintains a secure log of:
    - Files indexed
    - Queries performed
    - Data exports
    - Configuration changes
    """
    
    def __init__(self, data_dir: Path, encrypted_storage: EncryptedStorage | None = None):
        self.log_path = data_dir / "audit.log"
        self.encrypted_log_path = data_dir / "audit.log.enc"
        self.storage = encrypted_storage
        self._ensure_log_exists()
    
    def _ensure_log_exists(self) -> None:
        """Ensure audit log file exists."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.touch()
    
    def _format_entry(self, action: str, details: dict) -> str:
        """Format a log entry."""
        timestamp = datetime.now().isoformat()
        details_str = json.dumps(details, default=str)
        return f"{timestamp} | {action} | {details_str}\n"
    
    def log(self, action: str, details: dict | None = None) -> None:
        """
        Log an audit event.
        
        Actions:
        - FILE_INDEXED: A file was indexed
        - FILE_DELETED: A file was removed from index
        - QUERY_PERFORMED: A search query was executed
        - DATA_EXPORTED: User exported their data
        - DATA_DELETED: User deleted their data
        - CONFIG_CHANGED: Configuration was modified
        - SCAN_STARTED: Device scan initiated
        - SCAN_COMPLETED: Device scan finished
        """
        entry = self._format_entry(action, details or {})
        
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)
    
    def log_file_indexed(self, filepath: str, chunks: int) -> None:
        """Log that a file was indexed."""
        self.log("FILE_INDEXED", {
            "filepath": filepath,
            "chunks": chunks,
        })
    
    def log_file_deleted(self, filepath: str) -> None:
        """Log that a file was removed from index."""
        self.log("FILE_DELETED", {"filepath": filepath})
    
    def log_query(self, query: str, results_count: int) -> None:
        """Log a search query (without storing the actual query for privacy)."""
        self.log("QUERY_PERFORMED", {
            "query_hash": hashlib.sha256(query.encode()).hexdigest()[:16],
            "results_count": results_count,
        })
    
    def log_data_export(self, export_type: str, path: str) -> None:
        """Log a data export."""
        self.log("DATA_EXPORTED", {
            "export_type": export_type,
            "path": path,
        })
    
    def log_data_deletion(self, deletion_type: str) -> None:
        """Log data deletion."""
        self.log("DATA_DELETED", {"deletion_type": deletion_type})
    
    def get_recent_entries(self, count: int = 100) -> list[str]:
        """Get recent audit log entries."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return lines[-count:]
        except Exception:
            return []
    
    def get_stats(self) -> dict:
        """Get statistics from audit log."""
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            stats = {
                "total_entries": len(lines),
                "files_indexed": 0,
                "queries_performed": 0,
                "exports": 0,
            }
            
            for line in lines:
                if "FILE_INDEXED" in line:
                    stats["files_indexed"] += 1
                elif "QUERY_PERFORMED" in line:
                    stats["queries_performed"] += 1
                elif "DATA_EXPORTED" in line:
                    stats["exports"] += 1
            
            return stats
        except Exception:
            return {}


# ============================================================================
# Singleton Instances
# ============================================================================

_key_manager: KeyManager | None = None
_encrypted_storage: EncryptedStorage | None = None
_audit_logger: AuditLogger | None = None


def get_key_manager(data_dir: Path) -> KeyManager:
    """Get singleton KeyManager instance."""
    global _key_manager
    if _key_manager is None:
        _key_manager = KeyManager(data_dir)
    return _key_manager


def get_encrypted_storage(data_dir: Path) -> EncryptedStorage:
    """Get singleton EncryptedStorage instance."""
    global _encrypted_storage
    if _encrypted_storage is None:
        key_manager = get_key_manager(data_dir)
        _encrypted_storage = EncryptedStorage(key_manager)
    return _encrypted_storage


def get_audit_logger(data_dir: Path) -> AuditLogger:
    """Get singleton AuditLogger instance."""
    global _audit_logger
    if _audit_logger is None:
        storage = get_encrypted_storage(data_dir)
        _audit_logger = AuditLogger(data_dir, storage)
    return _audit_logger
