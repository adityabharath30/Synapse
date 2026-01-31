"""
Scanner Configuration Manager.

Loads and validates the scanner_config.yaml file for device-wide file scanning.
Provides security checks and path resolution.
"""
from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("rag.scanner")

# Default config path
CONFIG_PATH = Path(__file__).resolve().parents[1] / "scanner_config.yaml"


@dataclass
class ScannerConfig:
    """Configuration for the device-wide file scanner."""
    
    # Directories to scan (resolved to absolute paths)
    scan_directories: list[Path] = field(default_factory=list)
    
    # Security exclusions
    excluded_directories: list[str] = field(default_factory=list)
    excluded_file_patterns: list[str] = field(default_factory=list)
    
    # File size limits
    max_file_size_mb: float = 50.0
    min_file_size_bytes: int = 100
    
    # Scan behavior
    recursive: bool = True
    follow_symlinks: bool = False
    max_depth: int = 10
    
    # Image processing
    process_images: bool = False  # Disabled by default for privacy
    max_image_size_mb: float = 10.0
    image_scan_directories: list[Path] = field(default_factory=list)
    
    # Image dimension filtering (skip small icons/thumbnails)
    min_image_width: int = 200
    min_image_height: int = 200
    
    # Scheduling
    full_scan_interval_hours: int = 24
    watcher_debounce_seconds: int = 5
    
    # Performance
    batch_size: int = 10
    batch_pause_seconds: float = 1.0
    parallel_workers: int = 4  # Number of parallel workers for file processing
    
    # Privacy settings
    local_only_mode: bool = False  # If True, never use cloud APIs
    enable_audit_logging: bool = True
    encrypt_index: bool = False  # Encrypt stored index
    
    def __post_init__(self):
        """Set up default exclusions if none provided."""
        if not self.excluded_directories:
            self.excluded_directories = self._default_excluded_dirs()
        if not self.excluded_file_patterns:
            self.excluded_file_patterns = self._default_excluded_patterns()
    
    @staticmethod
    def _default_excluded_dirs() -> list[str]:
        """Default directories to never scan."""
        return [
            # Security-sensitive
            "**/.ssh", "**/.gnupg", "**/.gpg", "**/.aws", "**/.azure",
            "**/.config/gcloud", "**/.kube", "**/Keychains",
            "**/.password-store", "**/.vault", "**/.secrets",
            
            # Development directories
            "**/node_modules", "**/.git", "**/venv", "**/.venv",
            "**/env", "**/__pycache__", "**/.tox", "**/dist",
            "**/build", "**/.eggs", "**/target",
            
            # System and caches
            "**/Library/Caches", "**/Library/Application Support/*/Cache*",
            "**/.Trash", "**/.cache", "**/tmp", "**/temp",
            
            # Application bundles and resources (contain icons)
            "**/*.app", "**/*.framework", "**/Resources",
            "**/images", "**/icons", "**/assets", "**/thumbnails",
        ]
    
    @staticmethod
    def _default_excluded_patterns() -> list[str]:
        """Default file patterns to never index."""
        return [
            # Credentials and keys
            "*.pem", "*.key", "*.p12", "*.pfx", "*.keystore", "*.jks",
            "*_rsa", "*_ed25519", "*_ecdsa", "*_dsa", "*.ppk",
            
            # Environment and secrets
            ".env", ".env.*", "*.env", ".netrc", ".npmrc", ".pypirc",
            "credentials*.json", "*credentials*", "*secret*", "*token*",
            "*password*", "*api_key*", "*apikey*", "*.htpasswd",
            
            # macOS system files
            ".DS_Store", "*.keychain", "*.keychain-db",
            
            # Temporary files
            "*.tmp", "*.temp", "*.swp", "*.swo", "*~", "*.bak",
            
            # UI icons and toolbar buttons (waste of Vision API)
            "*toolbarButton*", "*ToolbarButton*", "*toolbar-*",
            "*icon*", "*Icon*", "*-icon.*", "*_icon.*",
            "*logo*", "*Logo*", "*button*", "*Button*",
            "*@2x.*", "*@3x.*", "*-2x.*", "*_2x.*",
            "*thumbnail*", "*Thumbnail*", "*badge*", "*Badge*",
            
            # Binary and archive files
            "*.zip", "*.tar", "*.tar.gz", "*.tgz", "*.rar", "*.7z",
            "*.dmg", "*.iso", "*.pkg", "*.app", "*.exe", "*.dll",
            "*.so", "*.dylib",
        ]
    
    def is_directory_excluded(self, dir_path: Path) -> bool:
        """Check if a directory should be excluded from scanning."""
        dir_str = str(dir_path)
        dir_name = dir_path.name
        
        for pattern in self.excluded_directories:
            # Check if pattern matches the full path or just the directory name
            if fnmatch.fnmatch(dir_str, pattern):
                return True
            if fnmatch.fnmatch(dir_name, pattern.replace("**/", "")):
                return True
            # Check each component of the path
            for part in dir_path.parts:
                if fnmatch.fnmatch(part, pattern.replace("**/", "")):
                    return True
        
        return False
    
    def is_file_excluded(self, file_path: Path) -> bool:
        """Check if a file should be excluded from indexing."""
        filename = file_path.name
        file_str = str(file_path).lower()
        
        for pattern in self.excluded_file_patterns:
            pattern_lower = pattern.lower()
            # Match against filename
            if fnmatch.fnmatch(filename.lower(), pattern_lower):
                return True
            # Match against full path for patterns with path separators
            if fnmatch.fnmatch(file_str, f"**/{pattern_lower}"):
                return True
        
        return False
    
    def is_file_size_valid(self, file_path: Path) -> bool:
        """Check if file size is within allowed limits."""
        try:
            size = file_path.stat().st_size
            max_bytes = self.max_file_size_mb * 1024 * 1024
            return self.min_file_size_bytes <= size <= max_bytes
        except OSError:
            return False
    
    def should_process_image(self, file_path: Path) -> bool:
        """Check if an image file should be processed with vision API."""
        if not self.process_images:
            return False
        
        # Local-only mode disables cloud APIs
        if self.local_only_mode:
            return False
        
        # Check file size
        try:
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if size_mb > self.max_image_size_mb:
                return False
        except OSError:
            return False
        
        # Check if in allowed image directories
        if self.image_scan_directories:
            in_allowed = any(
                self._is_subpath(file_path, img_dir)
                for img_dir in self.image_scan_directories
            )
            if not in_allowed:
                return False
        
        # Check image dimensions (skip small icons)
        if not self.is_image_large_enough(file_path):
            return False
        
        return True
    
    def is_image_large_enough(self, file_path: Path) -> bool:
        """
        Check if image meets minimum dimension requirements.
        
        Skips small icons, thumbnails, and UI elements.
        Uses PIL for fast dimension reading without loading full image.
        """
        try:
            from PIL import Image
            
            with Image.open(file_path) as img:
                width, height = img.size
                return (
                    width >= self.min_image_width and 
                    height >= self.min_image_height
                )
        except ImportError:
            # PIL not installed, fall back to file size heuristic
            # Icons are typically < 50KB
            try:
                size = file_path.stat().st_size
                return size > 50 * 1024  # > 50KB probably not an icon
            except OSError:
                return False
        except Exception:
            # Can't read image, skip it
            return False
    
    @staticmethod
    def _is_subpath(path: Path, parent: Path) -> bool:
        """Check if path is under parent directory."""
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False
    
    def get_scan_directories(self) -> list[Path]:
        """Get list of directories to scan, filtered by existence."""
        valid_dirs = []
        for dir_path in self.scan_directories:
            if dir_path.exists() and dir_path.is_dir():
                valid_dirs.append(dir_path)
            else:
                logger.warning("Scan directory does not exist: %s", dir_path)
        return valid_dirs


def _expand_path(path_str: str) -> Path:
    """Expand ~ and environment variables in path string."""
    expanded = os.path.expanduser(os.path.expandvars(path_str))
    return Path(expanded).resolve()


def _load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load configuration from YAML file."""
    if not config_path.exists():
        logger.warning("Config file not found: %s, using defaults", config_path)
        return {}
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return config if config else {}
    except yaml.YAMLError as e:
        logger.error("Failed to parse config file: %s", e)
        return {}
    except Exception as e:
        logger.error("Failed to load config file: %s", e)
        return {}


def load_config(config_path: Path | None = None) -> ScannerConfig:
    """
    Load scanner configuration from YAML file.
    
    Args:
        config_path: Path to config file. Defaults to scanner_config.yaml in project root.
    
    Returns:
        ScannerConfig instance with loaded or default values.
    """
    path = config_path or CONFIG_PATH
    raw = _load_yaml_config(path)
    
    # Parse scan directories
    scan_dirs = []
    for dir_str in raw.get("scan_directories", ["~/Documents", "~/Desktop"]):
        scan_dirs.append(_expand_path(dir_str))
    
    # Parse image scan directories
    image_dirs = []
    for dir_str in raw.get("image_scan_directories", []):
        image_dirs.append(_expand_path(dir_str))
    
    return ScannerConfig(
        scan_directories=scan_dirs,
        excluded_directories=raw.get("excluded_directories", []),
        excluded_file_patterns=raw.get("excluded_file_patterns", []),
        max_file_size_mb=raw.get("max_file_size_mb", 50.0),
        min_file_size_bytes=raw.get("min_file_size_bytes", 100),
        recursive=raw.get("recursive", True),
        follow_symlinks=raw.get("follow_symlinks", False),
        max_depth=raw.get("max_depth", 10),
        process_images=raw.get("process_images", False),
        max_image_size_mb=raw.get("max_image_size_mb", 10.0),
        image_scan_directories=image_dirs,
        min_image_width=raw.get("min_image_width", 200),
        min_image_height=raw.get("min_image_height", 200),
        full_scan_interval_hours=raw.get("full_scan_interval_hours", 24),
        watcher_debounce_seconds=raw.get("watcher_debounce_seconds", 5),
        batch_size=raw.get("batch_size", 10),
        batch_pause_seconds=raw.get("batch_pause_seconds", 1.0),
        parallel_workers=raw.get("parallel_workers", 4),
        local_only_mode=raw.get("local_only_mode", False),
        enable_audit_logging=raw.get("enable_audit_logging", True),
        encrypt_index=raw.get("encrypt_index", False),
    )


# Singleton config instance
_config: ScannerConfig | None = None


def get_config() -> ScannerConfig:
    """Get the singleton scanner configuration."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> ScannerConfig:
    """Reload configuration from disk."""
    global _config
    _config = load_config()
    return _config
