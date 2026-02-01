#!/usr/bin/env python3
"""
Synapse Launcher with Global Hotkey.

Runs in the background and listens for a hotkey to launch the Synapse UI.
Default hotkey: Cmd+Shift+Space (macOS) or Ctrl+Shift+Space (Windows/Linux)

Usage:
    python scripts/launcher.py

The launcher will:
1. Pre-load the search service for instant startup
2. Listen for the global hotkey
3. Launch the Synapse UI when triggered
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False
    print("⚠️  pynput not installed. Install with: pip install pynput")
    print("   Running Synapse UI directly instead...")


# Pre-load search service for faster startup
_search_service = None
_loading = False


def preload_search_service():
    """Pre-load the search service in background."""
    global _search_service, _loading
    _loading = True
    try:
        from app.search_service import SearchService
        _search_service = SearchService()
        print("✅ Search service pre-loaded")
    except Exception as e:
        print(f"⚠️  Failed to pre-load search service: {e}")
    finally:
        _loading = False


def launch_synapse():
    """Launch the Synapse UI."""
    print("🔍 Launching Synapse...")
    
    # Run the UI script
    ui_script = ROOT_DIR / "ui" / "synapse_ui.py"
    subprocess.Popen(
        [sys.executable, str(ui_script)],
        cwd=str(ROOT_DIR),
        start_new_session=True,
    )


def on_hotkey():
    """Callback when hotkey is pressed."""
    launch_synapse()


def run_with_hotkey():
    """Run the launcher with global hotkey listener."""
    print("=" * 50)
    print("🚀 Synapse Launcher")
    print("=" * 50)
    print()
    print("Hotkey: Cmd+Shift+Space (macOS) or Ctrl+Shift+Space")
    print("Press the hotkey to open Synapse")
    print("Press Ctrl+C to quit")
    print()
    
    # Pre-load search service
    print("⏳ Pre-loading search service...")
    preload_thread = threading.Thread(target=preload_search_service, daemon=True)
    preload_thread.start()
    
    # Define hotkey combinations
    # macOS: Cmd+Shift+Space
    # Windows/Linux: Ctrl+Shift+Space
    HOTKEY_COMBINATIONS = [
        {keyboard.Key.cmd, keyboard.Key.shift, keyboard.Key.space},  # macOS
        {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space},  # Windows/Linux
    ]
    
    current_keys = set()
    
    def on_press(key):
        current_keys.add(key)
        for combo in HOTKEY_COMBINATIONS:
            if combo.issubset(current_keys):
                on_hotkey()
                current_keys.clear()
                break
    
    def on_release(key):
        try:
            current_keys.discard(key)
        except KeyError:
            pass
    
    # Start listener
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")


def run_direct():
    """Run the Synapse UI directly (no hotkey)."""
    launch_synapse()


def main():
    """Main entry point."""
    if PYNPUT_AVAILABLE:
        run_with_hotkey()
    else:
        run_direct()


if __name__ == "__main__":
    main()
