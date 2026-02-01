"""
Settings UI for Synapse.

Provides a graphical interface to configure scanner settings
instead of editing YAML files manually.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False
    print("Settings UI requires CustomTkinter: pip install customtkinter")
    sys.exit(1)

import yaml
from app.config import SCANNER_CONFIG_PATH, DATA_DIR


# Color scheme matching synapse_ui
COLORS = {
    "bg": "#1a1a1a",
    "bg_secondary": "#252525",
    "bg_hover": "#333333",
    "text": "#ffffff",
    "text_secondary": "#999999",
    "text_dim": "#666666",
    "accent": "#0a84ff",
    "border": "#3a3a3a",
    "success": "#30d158",
    "warning": "#ffd60a",
    "error": "#ff453a",
}


class SettingsUI:
    """Settings configuration UI."""

    def __init__(self) -> None:
        self.config = self._load_config()
        self._changes_made = False

        # Configure appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Create window
        self.root = ctk.CTk()
        self.root.title("Synapse Settings")
        self.root.geometry("600x700")
        self.root.configure(fg_color=COLORS["bg"])
        
        # Center on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 600) // 2
        y = (self.root.winfo_screenheight() - 700) // 3
        self.root.geometry(f"600x700+{x}+{y}")

        self._build_ui()

    def _load_config(self) -> dict:
        """Load configuration from YAML."""
        if SCANNER_CONFIG_PATH.exists():
            try:
                with open(SCANNER_CONFIG_PATH) as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return {}
        return {}

    def _save_config(self) -> None:
        """Save configuration to YAML."""
        try:
            with open(SCANNER_CONFIG_PATH, "w") as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
            self._show_status("✅ Settings saved!", COLORS["success"])
            self._changes_made = False
        except Exception as e:
            self._show_status(f"❌ Error: {e}", COLORS["error"])

    def _build_ui(self) -> None:
        """Build the settings UI."""
        # Main scrollable container
        main_frame = ctk.CTkScrollableFrame(
            self.root,
            fg_color=COLORS["bg"],
        )
        main_frame.pack(fill="both", expand=True, padx=16, pady=16)

        # Title
        title = ctk.CTkLabel(
            main_frame,
            text="⚙️ Settings",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["text"],
        )
        title.pack(anchor="w", pady=(0, 20))

        # ======== Scan Directories Section ========
        self._create_section_header(main_frame, "📁 Scan Directories")
        
        dirs_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_secondary"], corner_radius=8)
        dirs_frame.pack(fill="x", pady=(0, 16))
        
        dirs_help = ctk.CTkLabel(
            dirs_frame,
            text="Directories to scan for documents (one per line):",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        dirs_help.pack(anchor="w", padx=12, pady=(12, 4))
        
        self.dirs_textbox = ctk.CTkTextbox(
            dirs_frame,
            height=100,
            font=ctk.CTkFont(family="Monaco", size=12),
            fg_color=COLORS["bg"],
            text_color=COLORS["text"],
        )
        self.dirs_textbox.pack(fill="x", padx=12, pady=(0, 12))
        
        # Populate with current dirs
        scan_dirs = self.config.get("scan_directories", [])
        self.dirs_textbox.insert("1.0", "\n".join(scan_dirs))
        self.dirs_textbox.bind("<KeyRelease>", lambda _: self._mark_changed())
        
        # Add common directory buttons
        btn_frame = ctk.CTkFrame(dirs_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))
        
        for name, path in [("+ Documents", "~/Documents"), ("+ Desktop", "~/Desktop"), ("+ Downloads", "~/Downloads")]:
            btn = ctk.CTkButton(
                btn_frame,
                text=name,
                width=100,
                height=28,
                fg_color=COLORS["bg_hover"],
                hover_color=COLORS["accent"],
                command=lambda p=path: self._add_directory(p),
            )
            btn.pack(side="left", padx=(0, 8))

        # ======== Image Processing Section ========
        self._create_section_header(main_frame, "🖼️ Image Processing")
        
        img_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_secondary"], corner_radius=8)
        img_frame.pack(fill="x", pady=(0, 16))
        
        self.process_images_var = ctk.BooleanVar(value=self.config.get("process_images", False))
        img_switch = ctk.CTkSwitch(
            img_frame,
            text="Process images (uses OpenAI Vision API)",
            variable=self.process_images_var,
            command=self._mark_changed,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text"],
        )
        img_switch.pack(anchor="w", padx=12, pady=12)
        
        img_help = ctk.CTkLabel(
            img_frame,
            text="⚠️ Image processing sends images to OpenAI's servers",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["warning"],
        )
        img_help.pack(anchor="w", padx=12, pady=(0, 12))

        # ======== Privacy Section ========
        self._create_section_header(main_frame, "🔒 Privacy & Security")
        
        privacy_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_secondary"], corner_radius=8)
        privacy_frame.pack(fill="x", pady=(0, 16))
        
        self.local_only_var = ctk.BooleanVar(value=self.config.get("local_only_mode", False))
        local_switch = ctk.CTkSwitch(
            privacy_frame,
            text="Local-only mode (no cloud APIs)",
            variable=self.local_only_var,
            command=self._mark_changed,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text"],
        )
        local_switch.pack(anchor="w", padx=12, pady=(12, 4))
        
        self.audit_var = ctk.BooleanVar(value=self.config.get("enable_audit_logging", True))
        audit_switch = ctk.CTkSwitch(
            privacy_frame,
            text="Enable audit logging",
            variable=self.audit_var,
            command=self._mark_changed,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text"],
        )
        audit_switch.pack(anchor="w", padx=12, pady=4)
        
        self.encrypt_var = ctk.BooleanVar(value=self.config.get("encrypt_index", False))
        encrypt_switch = ctk.CTkSwitch(
            privacy_frame,
            text="Encrypt index storage",
            variable=self.encrypt_var,
            command=self._mark_changed,
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text"],
        )
        encrypt_switch.pack(anchor="w", padx=12, pady=(4, 12))

        # ======== Performance Section ========
        self._create_section_header(main_frame, "⚡ Performance")
        
        perf_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_secondary"], corner_radius=8)
        perf_frame.pack(fill="x", pady=(0, 16))
        
        workers_label = ctk.CTkLabel(
            perf_frame,
            text="Parallel workers:",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text"],
        )
        workers_label.pack(anchor="w", padx=12, pady=(12, 4))
        
        self.workers_slider = ctk.CTkSlider(
            perf_frame,
            from_=1,
            to=8,
            number_of_steps=7,
            command=self._on_slider_change,
        )
        self.workers_slider.set(self.config.get("parallel_workers", 4))
        self.workers_slider.pack(fill="x", padx=12, pady=(0, 4))
        
        self.workers_value = ctk.CTkLabel(
            perf_frame,
            text=f"{int(self.workers_slider.get())} workers",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
        )
        self.workers_value.pack(anchor="w", padx=12, pady=(0, 12))

        # ======== API Key Section ========
        self._create_section_header(main_frame, "🔑 API Configuration")
        
        api_frame = ctk.CTkFrame(main_frame, fg_color=COLORS["bg_secondary"], corner_radius=8)
        api_frame.pack(fill="x", pady=(0, 16))
        
        api_label = ctk.CTkLabel(
            api_frame,
            text="OpenAI API Key:",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text"],
        )
        api_label.pack(anchor="w", padx=12, pady=(12, 4))
        
        self.api_entry = ctk.CTkEntry(
            api_frame,
            placeholder_text="sk-...",
            show="•",
            font=ctk.CTkFont(family="Monaco", size=12),
            fg_color=COLORS["bg"],
            text_color=COLORS["text"],
        )
        self.api_entry.pack(fill="x", padx=12, pady=(0, 4))
        
        api_help = ctk.CTkLabel(
            api_frame,
            text="Stored securely in macOS Keychain",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
        )
        api_help.pack(anchor="w", padx=12, pady=(0, 8))
        
        save_key_btn = ctk.CTkButton(
            api_frame,
            text="Save API Key",
            width=120,
            fg_color=COLORS["accent"],
            command=self._save_api_key,
        )
        save_key_btn.pack(anchor="w", padx=12, pady=(0, 12))

        # ======== Status Bar ========
        self.status_label = ctk.CTkLabel(
            self.root,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
        )
        self.status_label.pack(side="bottom", pady=(0, 8))

        # ======== Action Buttons ========
        btn_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        btn_frame.pack(side="bottom", fill="x", padx=16, pady=8)
        
        save_btn = ctk.CTkButton(
            btn_frame,
            text="Save Settings",
            width=140,
            height=36,
            fg_color=COLORS["accent"],
            command=self._on_save,
        )
        save_btn.pack(side="right")
        
        reset_btn = ctk.CTkButton(
            btn_frame,
            text="Reset to Defaults",
            width=140,
            height=36,
            fg_color=COLORS["bg_hover"],
            hover_color=COLORS["error"],
            command=self._on_reset,
        )
        reset_btn.pack(side="right", padx=(0, 8))

    def _create_section_header(self, parent, text: str) -> None:
        """Create a section header."""
        label = ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
        )
        label.pack(anchor="w", pady=(16, 8))

    def _add_directory(self, path: str) -> None:
        """Add a directory to the scan list."""
        current = self.dirs_textbox.get("1.0", "end").strip()
        if path not in current:
            if current:
                self.dirs_textbox.insert("end", f"\n{path}")
            else:
                self.dirs_textbox.insert("1.0", path)
            self._mark_changed()

    def _mark_changed(self) -> None:
        """Mark that changes have been made."""
        self._changes_made = True
        self._show_status("Unsaved changes", COLORS["warning"])

    def _on_slider_change(self, value: float) -> None:
        """Handle slider change."""
        self.workers_value.configure(text=f"{int(value)} workers")
        self._mark_changed()

    def _on_save(self) -> None:
        """Save all settings."""
        # Update config dict
        dirs_text = self.dirs_textbox.get("1.0", "end").strip()
        self.config["scan_directories"] = [d.strip() for d in dirs_text.split("\n") if d.strip()]
        self.config["process_images"] = self.process_images_var.get()
        self.config["local_only_mode"] = self.local_only_var.get()
        self.config["enable_audit_logging"] = self.audit_var.get()
        self.config["encrypt_index"] = self.encrypt_var.get()
        self.config["parallel_workers"] = int(self.workers_slider.get())
        
        self._save_config()

    def _on_reset(self) -> None:
        """Reset to default settings."""
        # Clear and reset
        self.dirs_textbox.delete("1.0", "end")
        self.dirs_textbox.insert("1.0", "~/Documents\n~/Desktop")
        self.process_images_var.set(False)
        self.local_only_var.set(False)
        self.audit_var.set(True)
        self.encrypt_var.set(False)
        self.workers_slider.set(4)
        self.workers_value.configure(text="4 workers")
        self._mark_changed()

    def _save_api_key(self) -> None:
        """Save API key to keychain."""
        api_key = self.api_entry.get().strip()
        if not api_key:
            self._show_status("❌ Please enter an API key", COLORS["error"])
            return
        
        try:
            from app.security import get_key_manager
            km = get_key_manager(DATA_DIR)
            km.set_api_key("OPENAI_API_KEY", api_key)
            self.api_entry.delete(0, "end")
            self._show_status("✅ API key saved to Keychain!", COLORS["success"])
        except Exception as e:
            self._show_status(f"❌ Error: {e}", COLORS["error"])

    def _show_status(self, text: str, color: str = COLORS["text_secondary"]) -> None:
        """Show status message."""
        self.status_label.configure(text=text, text_color=color)

    def run(self) -> None:
        """Run the settings UI."""
        self.root.mainloop()


def main():
    """Launch the settings UI."""
    if not CTK_AVAILABLE:
        print("Settings UI requires CustomTkinter")
        print("Install with: pip install customtkinter")
        sys.exit(1)
    
    app = SettingsUI()
    app.run()


if __name__ == "__main__":
    main()
