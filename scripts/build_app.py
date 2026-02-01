#!/usr/bin/env python3
"""
macOS App Builder for Synapse.

Creates a standalone .app bundle using PyInstaller.
The resulting app can be distributed without requiring Python installation.

Usage:
    python scripts/build_app.py          # Build the app
    python scripts/build_app.py --dmg    # Build app + create DMG installer
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def check_dependencies() -> bool:
    """Check if required build tools are installed."""
    try:
        import PyInstaller
        print(f"✅ PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("❌ PyInstaller not found")
        print("   Install with: pip install pyinstaller")
        return False


def create_spec_file() -> Path:
    """Create PyInstaller spec file."""
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Synapse.
"""

block_cipher = None

# Collect data files
datas = [
    ('{ROOT_DIR}/scanner_config.yaml', '.'),
    ('{ROOT_DIR}/requirements.txt', '.'),
]

# Hidden imports needed by the app
hiddenimports = [
    'sentence_transformers',
    'transformers',
    'torch',
    'faiss',
    'sklearn',
    'sklearn.utils._cython_blas',
    'sklearn.neighbors.typedefs',
    'sklearn.neighbors._partition_nodes',
    'customtkinter',
    'PIL',
    'PIL.Image',
    'cryptography',
    'keyring',
    'keyring.backends',
    'keyring.backends.macOS',
]

a = Analysis(
    ['{ROOT_DIR}/ui/synapse_ui.py'],
    pathex=['{ROOT_DIR}'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=['matplotlib', 'notebook', 'jupyter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Synapse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No terminal window
    disable_windowed_traceback=False,
    argv_emulation=True,  # macOS argv emulation
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Synapse',
)

app = BUNDLE(
    coll,
    name='Synapse.app',
    icon='{ROOT_DIR}/assets/icon.icns' if Path('{ROOT_DIR}/assets/icon.icns').exists() else None,
    bundle_identifier='com.synapse.app',
    info_plist={{
        'CFBundleName': 'Synapse',
        'CFBundleDisplayName': 'Synapse',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'NSAppleEventsUsageDescription': 'Synapse needs to control other apps to open documents.',
        'NSDocumentsFolderUsageDescription': 'Synapse needs access to your Documents folder to index files.',
        'NSDesktopFolderUsageDescription': 'Synapse needs access to your Desktop folder to index files.',
    }},
)
'''
    
    spec_path = ROOT_DIR / "Synapse.spec"
    spec_path.write_text(spec_content)
    print(f"✅ Created spec file: {spec_path}")
    return spec_path


def build_app(spec_path: Path) -> Path | None:
    """Build the app using PyInstaller."""
    print("\n🔨 Building macOS app...")
    print("   This may take several minutes...\n")
    
    try:
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller",
                "--clean",
                "--noconfirm",
                str(spec_path),
            ],
            cwd=ROOT_DIR,
            check=True,
        )
        
        app_path = ROOT_DIR / "dist" / "Synapse.app"
        if app_path.exists():
            print(f"\n✅ App built successfully: {app_path}")
            return app_path
        else:
            print("\n❌ Build failed: app not found")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Build failed: {e}")
        return None


def create_dmg(app_path: Path) -> Path | None:
    """Create a DMG installer."""
    print("\n📦 Creating DMG installer...")
    
    dmg_path = ROOT_DIR / "dist" / "Synapse-Installer.dmg"
    
    # Remove old DMG if exists
    if dmg_path.exists():
        dmg_path.unlink()
    
    try:
        # Create DMG using hdiutil
        subprocess.run(
            [
                "hdiutil", "create",
                "-volname", "Synapse",
                "-srcfolder", str(app_path),
                "-ov",
                "-format", "UDZO",
                str(dmg_path),
            ],
            check=True,
        )
        
        print(f"✅ DMG created: {dmg_path}")
        return dmg_path
        
    except subprocess.CalledProcessError as e:
        print(f"❌ DMG creation failed: {e}")
        return None


def create_assets_dir() -> None:
    """Create assets directory with placeholder."""
    assets_dir = ROOT_DIR / "assets"
    assets_dir.mkdir(exist_ok=True)
    
    readme = assets_dir / "README.md"
    if not readme.exists():
        readme.write_text("""# Assets

Place your app icon here as `icon.icns`.

To create an icns file from a PNG:
```bash
# Create iconset folder
mkdir icon.iconset

# Create various sizes (assumes icon.png is 1024x1024)
sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 icon.png --out icon.iconset/icon_512x512@2x.png

# Create icns
iconutil -c icns icon.iconset
```
""")
        print(f"✅ Created assets directory with instructions")


def main():
    parser = argparse.ArgumentParser(description="Build Synapse macOS app")
    parser.add_argument("--dmg", action="store_true", help="Also create DMG installer")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts first")
    args = parser.parse_args()
    
    print("=" * 60)
    print("Synapse - macOS App Builder")
    print("=" * 60)
    
    # Clean if requested
    if args.clean:
        print("\n🧹 Cleaning build artifacts...")
        for path in ["build", "dist", "Synapse.spec"]:
            full_path = ROOT_DIR / path
            if full_path.exists():
                if full_path.is_dir():
                    shutil.rmtree(full_path)
                else:
                    full_path.unlink()
                print(f"   Removed: {path}")
    
    # Check dependencies
    print("\n📋 Checking dependencies...")
    if not check_dependencies():
        print("\n⚠️  Install missing dependencies and try again")
        sys.exit(1)
    
    # Create assets directory
    create_assets_dir()
    
    # Create spec file
    spec_path = create_spec_file()
    
    # Build app
    app_path = build_app(spec_path)
    if not app_path:
        sys.exit(1)
    
    # Create DMG if requested
    if args.dmg:
        dmg_path = create_dmg(app_path)
    
    # Summary
    print("\n" + "=" * 60)
    print("Build Summary")
    print("=" * 60)
    print(f"App location: {app_path}")
    if args.dmg:
        print(f"DMG location: {ROOT_DIR / 'dist' / 'Synapse-Installer.dmg'}")
    print("\nTo run the app:")
    print(f"  open '{app_path}'")
    print("\nOr double-click it in Finder.")


if __name__ == "__main__":
    main()
