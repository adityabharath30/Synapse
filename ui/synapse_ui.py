"""
Synapse - Personal Semantic Search UI.

A modern, keyboard-first interface for personal semantic search.
Dark, minimal aesthetic with streaming answers.
"""
from __future__ import annotations

import subprocess
import sys
import threading
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
    import tkinter as tk
    from tkinter import ttk

from app.search_service import SearchService

# Try to import document utilities for source highlighting
try:
    from app.document_utils import open_document, find_answer_location
    DOCUMENT_UTILS_AVAILABLE = True
except ImportError:
    DOCUMENT_UTILS_AVAILABLE = False


# =============================================================================
# COLOR SCHEME (Dark Synapse)
# =============================================================================

COLORS = {
    "bg": "#1a1a1a",
    "bg_secondary": "#252525",
    "bg_hover": "#333333",
    "text": "#ffffff",
    "text_secondary": "#999999",
    "text_dim": "#666666",
    "accent": "#0a84ff",
    "accent_hover": "#409cff",
    "border": "#3a3a3a",
    "success": "#30d158",
    "warning": "#ffd60a",
    "error": "#ff453a",
}


# =============================================================================
# MODERN UI (CustomTkinter)
# =============================================================================

class ModernSynapseUI:
    """Modern Synapse UI using CustomTkinter."""

    def __init__(self) -> None:
        # Initialize search service in background
        self.search_service: SearchService | None = None
        self._init_thread = threading.Thread(target=self._init_search_service, daemon=True)
        self._init_thread.start()

        self._search_job: str | None = None
        self._documents: list[dict] = []
        self._selected_index: int = 0
        self._loading = False
        self._source_filepath: str = ""
        self._answer_text: str = ""  # Store answer for source highlighting
        self._source_page: int | None = None  # Store page number for PDFs
        self._streaming_mode: bool = True  # Enable streaming by default

        # Configure appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Create window
        self.root = ctk.CTk()
        self.root.title("Synapse")
        self.root.geometry("700x450")
        self.root.configure(fg_color=COLORS["bg"])
        
        # Center on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 700) // 2
        y = (self.root.winfo_screenheight() - 450) // 3
        self.root.geometry(f"700x450+{x}+{y}")
        
        # Always on top, no titlebar for clean look
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(False)  # Keep titlebar for now (can be removed)
        
        # Key bindings
        self.root.bind("<Escape>", lambda _: self.root.destroy())
        self.root.bind("<Return>", self._open_selected)
        self.root.bind("<Up>", self._select_prev)
        self.root.bind("<Down>", self._select_next)
        self.root.bind("<Command-k>", lambda _: self.entry.focus())
        self.root.bind("<Control-k>", lambda _: self.entry.focus())

        self._build_ui()

    def _init_search_service(self) -> None:
        """Initialize search service in background thread."""
        try:
            self.search_service = SearchService()
        except Exception as e:
            print(f"Failed to initialize search service: {e}")

    def _build_ui(self) -> None:
        """Build the UI components."""
        # Main container
        self.container = ctk.CTkFrame(self.root, fg_color=COLORS["bg"], corner_radius=12)
        self.container.pack(fill="both", expand=True, padx=8, pady=8)

        # Search bar frame
        search_frame = ctk.CTkFrame(self.container, fg_color=COLORS["bg_secondary"], corner_radius=10)
        search_frame.pack(fill="x", padx=12, pady=(12, 8))

        # Search icon
        search_icon = ctk.CTkLabel(
            search_frame,
            text="🔍",
            font=ctk.CTkFont(size=18),
            text_color=COLORS["text_secondary"],
        )
        search_icon.pack(side="left", padx=(12, 8), pady=12)

        # Search entry
        self.entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="Search your documents...",
            font=ctk.CTkFont(family="SF Pro", size=16),
            fg_color="transparent",
            border_width=0,
            text_color=COLORS["text"],
            placeholder_text_color=COLORS["text_dim"],
            height=40,
        )
        self.entry.pack(side="left", fill="x", expand=True, pady=8, padx=(0, 12))
        self.entry.bind("<KeyRelease>", self._on_key_release)
        self.entry.focus()

        # Loading indicator
        self.loading_label = ctk.CTkLabel(
            search_frame,
            text="",
            font=ctk.CTkFont(size=14),
            text_color=COLORS["accent"],
        )
        self.loading_label.pack(side="right", padx=12)

        # Answer card (shown when answer found)
        self.answer_frame = ctk.CTkFrame(
            self.container,
            fg_color=COLORS["bg_secondary"],
            corner_radius=10,
        )
        # Don't pack yet - will be shown when there's an answer

        # Answer text
        self.answer_label = ctk.CTkLabel(
            self.answer_frame,
            text="",
            font=ctk.CTkFont(family="SF Pro", size=17, weight="bold"),
            text_color=COLORS["text"],
            wraplength=640,
            justify="left",
            anchor="w",
        )
        self.answer_label.pack(fill="x", padx=16, pady=(16, 4))

        # Source label (clickable)
        self.source_label = ctk.CTkLabel(
            self.answer_frame,
            text="",
            font=ctk.CTkFont(family="SF Pro", size=12),
            text_color=COLORS["accent"],
            anchor="w",
            cursor="hand2",
        )
        self.source_label.pack(fill="x", padx=16, pady=(0, 16))
        self.source_label.bind("<Button-1>", self._open_source)

        # Message label (when no answer)
        self.message_label = ctk.CTkLabel(
            self.container,
            text="",
            font=ctk.CTkFont(family="SF Pro", size=13),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )

        # Documents header
        self.docs_header = ctk.CTkLabel(
            self.container,
            text="DOCUMENTS",
            font=ctk.CTkFont(family="SF Pro", size=11, weight="bold"),
            text_color=COLORS["text_dim"],
            anchor="w",
        )

        # Documents list
        self.docs_frame = ctk.CTkScrollableFrame(
            self.container,
            fg_color="transparent",
            corner_radius=0,
        )
        
        # Status bar
        self.status_frame = ctk.CTkFrame(
            self.container,
            fg_color="transparent",
            height=30,
        )
        self.status_frame.pack(side="bottom", fill="x", padx=12, pady=(4, 8))

        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="↑↓ Navigate  ⏎ Open  ⎋ Close",
            font=ctk.CTkFont(family="SF Pro", size=11),
            text_color=COLORS["text_dim"],
        )
        self.status_label.pack(side="left")

        self.mode_label = ctk.CTkLabel(
            self.status_frame,
            text="",
            font=ctk.CTkFont(family="SF Pro", size=11),
            text_color=COLORS["accent"],
        )
        self.mode_label.pack(side="right")
        
        # Settings button
        self.settings_btn = ctk.CTkButton(
            self.status_frame,
            text="⚙️",
            width=30,
            height=24,
            fg_color="transparent",
            hover_color=COLORS["bg_hover"],
            command=self._open_settings,
        )
        self.settings_btn.pack(side="right", padx=(0, 8))

    def _on_key_release(self, event) -> None:
        """Handle key release in search entry."""
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(200, self._run_search)

    def _run_search(self) -> None:
        """Execute search with streaming support."""
        query = self.entry.get().strip()
        self._search_job = None
        self._clear_results()

        if len(query) < 2:
            return

        if not self.search_service:
            self._show_message("Initializing... please wait")
            return

        self._loading = True
        self.loading_label.configure(text="⏳")

        if self._streaming_mode:
            # Use streaming search for better UX
            def on_documents(docs):
                """Called when documents are retrieved."""
                self.root.after(0, lambda: self._show_documents_early(docs))
            
            def on_status(status):
                """Called with status updates."""
                self.root.after(0, lambda: self.loading_label.configure(
                    text="🔍" if "Search" in status else "✨"
                ))
            
            def on_answer_token(char):
                """Called for each character - typewriter effect."""
                self.root.after(0, lambda c=char: self._append_answer_char(c))
            
            def on_complete(result):
                """Called when search completes."""
                self.root.after(0, lambda: self._display_results(result, streaming_done=True))
            
            def do_streaming_search():
                try:
                    self.search_service.answer_streaming(
                        query,
                        on_documents=on_documents,
                        on_status=on_status,
                        on_answer_token=on_answer_token,
                        on_complete=on_complete,
                        top_k=6,
                    )
                except Exception as e:
                    self.root.after(0, lambda: self._show_error(str(e)))
            
            threading.Thread(target=do_streaming_search, daemon=True).start()
        else:
            # Non-streaming search (fallback)
            def do_search():
                try:
                    result = self.search_service.answer(query, top_k=6)
                    self.root.after(0, lambda: self._display_results(result))
                except Exception as e:
                    self.root.after(0, lambda: self._show_error(str(e)))

            threading.Thread(target=do_search, daemon=True).start()
    
    def _show_documents_early(self, documents: list[dict]) -> None:
        """Show documents while extraction is in progress."""
        self._documents = documents
        if documents:
            # Show answer frame for streaming
            self.answer_frame.pack(fill="x", padx=12, pady=(0, 8))
            self.answer_label.configure(text="")
            self.source_label.configure(text="Finding answer...")
    
    def _append_answer_char(self, char: str) -> None:
        """Append a character to the streaming answer display."""
        current = self.answer_label.cget("text")
        self.answer_label.configure(text=current + char)

    def _display_results(self, payload: dict, streaming_done: bool = False) -> None:
        """Display search results."""
        self._loading = False
        self.loading_label.configure(text="")

        answerable = payload.get("answerable", False)
        answer = payload.get("answer", "")
        source = payload.get("source", "")
        filepath = payload.get("filepath", "")
        documents = payload.get("documents", [])
        mode = payload.get("mode", "")

        # Store source info for clicking and highlighting
        self._source_filepath = filepath
        self._answer_text = answer  # Store for source highlighting
        self._source_page = payload.get("source_page")  # Store page number if available

        # Show mode indicator
        mode_text = {"fact_lookup": "🎯 Fact", "fulltext": "📄 Browse", "summary": "📝 Summary"}.get(mode, "")
        self.mode_label.configure(text=mode_text)

        if answerable and answer:
            # Show answer card with source - NO document list
            self.answer_frame.pack(fill="x", padx=12, pady=(0, 8))
            
            # If streaming was used, answer is already displayed; otherwise set it
            if not streaming_done:
                self.answer_label.configure(text=answer)
            
            # Build source label with page number if available
            if source:
                source_text = f"📄 {source}"
                if self._source_page:
                    source_text += f" (page {self._source_page})"
                source_text += "  — click to open & highlight"
                self.source_label.configure(text=source_text)
            else:
                self.source_label.configure(text="")
            
            # Store only the source document for navigation
            self._documents = [{"filepath": filepath, "filename": source}] if filepath else []
            self._selected_index = 0
            
            # Hide document list since we only show the source
            self.message_label.pack_forget()
            self.docs_header.pack_forget()
            self.docs_frame.pack_forget()
        else:
            # Hide answer card, show message and document list
            self.answer_frame.pack_forget()
            self._documents = documents
            
            if documents:
                self._show_message("No direct answer found. Relevant documents:")
                self.docs_header.pack(fill="x", padx=16, pady=(8, 4))
                self.docs_frame.pack(fill="both", expand=True, padx=12, pady=(0, 4))
                self._populate_documents(documents)
            else:
                self._show_message("No results found")

    def _populate_documents(self, documents: list[dict]) -> None:
        """Populate document list."""
        # Clear existing
        for widget in self.docs_frame.winfo_children():
            widget.destroy()

        for idx, doc in enumerate(documents):
            row = DocumentRow(
                self.docs_frame,
                doc=doc,
                index=idx,
                selected=(idx == self._selected_index),
                on_click=self._on_doc_click,
            )
            row.pack(fill="x", pady=2)

    def _on_doc_click(self, index: int) -> None:
        """Handle document row click."""
        self._selected_index = index
        self._refresh_selection()
        self._open_selected(None)

    def _refresh_selection(self) -> None:
        """Refresh visual selection."""
        for idx, widget in enumerate(self.docs_frame.winfo_children()):
            if hasattr(widget, "set_selected"):
                widget.set_selected(idx == self._selected_index)

    def _show_message(self, text: str) -> None:
        """Show a message."""
        self.message_label.configure(text=text)
        self.message_label.pack(fill="x", padx=16, pady=(8, 4))

    def _show_error(self, text: str) -> None:
        """Show an error."""
        self._loading = False
        self.loading_label.configure(text="")
        self._show_message(f"❌ {text}")

    def _clear_results(self) -> None:
        """Clear all results."""
        self.answer_frame.pack_forget()
        self.message_label.pack_forget()
        self.docs_header.pack_forget()
        self.docs_frame.pack_forget()
        for widget in self.docs_frame.winfo_children():
            widget.destroy()
        self._documents = []
        self._selected_index = 0
        self._answer_text = ""
        self._source_page = None
        self.mode_label.configure(text="")

    def _select_prev(self, _) -> None:
        """Select previous document."""
        if not self._documents:
            return
        self._selected_index = max(0, self._selected_index - 1)
        self._refresh_selection()

    def _select_next(self, _) -> None:
        """Select next document."""
        if not self._documents:
            return
        self._selected_index = min(len(self._documents) - 1, self._selected_index + 1)
        self._refresh_selection()

    def _open_selected(self, _) -> None:
        """Open selected document."""
        if not self._documents or self._selected_index >= len(self._documents):
            return
        
        filepath = self._documents[self._selected_index].get("filepath", "")
        if filepath:
            try:
                subprocess.run(["open", filepath], check=False)
            except Exception as e:
                self._show_error(f"Could not open file: {e}")

    def _open_source(self, _) -> None:
        """Open the source document with answer highlighting."""
        if not self._source_filepath:
            return
        
        try:
            if DOCUMENT_UTILS_AVAILABLE and self._answer_text:
                # Use document utils to open with text search/highlighting
                # For PDFs, this will trigger find (Cmd+F) with the answer text
                search_text = self._get_search_text()
                success = open_document(self._source_filepath, search_text=search_text)
                if not success:
                    # Fallback to basic open
                    subprocess.run(["open", self._source_filepath], check=False)
            else:
                # Basic open without highlighting
                subprocess.run(["open", self._source_filepath], check=False)
        except Exception as e:
            self._show_error(f"Could not open file: {e}")
    
    def _get_search_text(self) -> str:
        """Get optimal search text for document highlighting."""
        if not self._answer_text:
            return ""
        
        # Get first meaningful phrase from the answer (first 5-8 words)
        # This works better for PDF search than full answer
        words = self._answer_text.split()
        
        if len(words) <= 6:
            return self._answer_text
        
        # Take first meaningful segment (avoid starting with common words)
        skip_starts = {"the", "a", "an", "is", "are", "was", "were", "it", "this", "that"}
        start_idx = 0
        for i, word in enumerate(words[:3]):
            if word.lower() not in skip_starts:
                start_idx = i
                break
        
        # Return 5-6 words for reliable PDF search
        return " ".join(words[start_idx:start_idx + 6])

    def _open_settings(self) -> None:
        """Open the settings UI."""
        try:
            # Launch settings in a separate process
            subprocess.Popen(
                [sys.executable, str(ROOT_DIR / "ui" / "settings_ui.py")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self._show_error(f"Could not open settings: {e}")

    def run(self) -> None:
        """Run the application."""
        self.root.mainloop()


class DocumentRow(ctk.CTkFrame):
    """A clickable document row."""

    def __init__(
        self,
        parent,
        doc: dict,
        index: int,
        selected: bool,
        on_click,
    ):
        super().__init__(
            parent,
            fg_color=COLORS["bg_hover"] if selected else "transparent",
            corner_radius=8,
            cursor="hand2",
        )
        
        self.doc = doc
        self.index = index
        self.on_click = on_click
        self._selected = selected

        # File icon + name
        name_frame = ctk.CTkFrame(self, fg_color="transparent")
        name_frame.pack(fill="x", padx=12, pady=(8, 2))

        icon = ctk.CTkLabel(
            name_frame,
            text="📄",
            font=ctk.CTkFont(size=14),
        )
        icon.pack(side="left")

        filename = ctk.CTkLabel(
            name_frame,
            text=doc.get("filename", "Unknown"),
            font=ctk.CTkFont(family="SF Pro", size=13, weight="bold"),
            text_color=COLORS["text"],
            anchor="w",
        )
        filename.pack(side="left", padx=(8, 0))

        # Preview
        preview = doc.get("preview", "")
        if preview:
            preview_label = ctk.CTkLabel(
                self,
                text=preview,
                font=ctk.CTkFont(family="SF Pro", size=12),
                text_color=COLORS["text_secondary"],
                anchor="w",
                wraplength=620,
            )
            preview_label.pack(fill="x", padx=(36, 12), pady=(0, 8))

        # Bind click
        self.bind("<Button-1>", lambda _: self.on_click(self.index))
        for child in self.winfo_children():
            child.bind("<Button-1>", lambda _: self.on_click(self.index))

    def set_selected(self, selected: bool) -> None:
        """Set selection state."""
        self._selected = selected
        self.configure(fg_color=COLORS["bg_hover"] if selected else "transparent")


# =============================================================================
# FALLBACK UI (Standard Tkinter)
# =============================================================================

class FallbackSynapseUI:
    """Fallback UI using standard tkinter (if CustomTkinter not available)."""

    def __init__(self) -> None:
        self.search_service = SearchService()
        self._search_job = None
        self._documents = []
        self._selected_index = 0

        self.root = tk.Tk()
        self.root.title("Synapse")
        self.root.geometry("700x400")
        self.root.configure(bg="#1e1e1e")
        self.root.attributes("-topmost", True)

        self.root.bind("<Escape>", lambda _: self.root.destroy())
        self.root.bind("<Return>", self._open_selected)
        self.root.bind("<Up>", self._select_prev)
        self.root.bind("<Down>", self._select_next)

        # Entry
        self.entry = ttk.Entry(self.root, font=("SF Pro", 16))
        self.entry.pack(fill="x", padx=12, pady=12)
        self.entry.bind("<KeyRelease>", self._on_key_release)
        self.entry.focus()

        # Answer
        self.answer_label = ttk.Label(self.root, text="", font=("SF Pro", 15), wraplength=660)
        self.answer_label.pack(fill="x", padx=12, pady=(0, 4))

        # Source
        self.source_label = ttk.Label(self.root, text="", font=("SF Pro", 11), foreground="#888")
        self.source_label.pack(fill="x", padx=12, pady=(0, 8))

        # Documents
        self.listbox = tk.Listbox(
            self.root,
            font=("SF Pro", 12),
            bg="#2a2a2a",
            fg="#e0e0e0",
            selectbackground="#0a84ff",
            borderwidth=0,
            highlightthickness=0,
        )
        self.listbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.listbox.bind("<Double-Button-1>", self._open_selected)

    def _on_key_release(self, event) -> None:
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        if self._search_job:
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(200, self._run_search)

    def _run_search(self) -> None:
        query = self.entry.get().strip()
        self._search_job = None
        self._clear()

        if len(query) < 2:
            return

        try:
            result = self.search_service.answer(query, top_k=6)
            self._display(result)
        except Exception as e:
            self.answer_label.configure(text=f"Error: {e}")

    def _display(self, payload: dict) -> None:
        answer = payload.get("answer", "")
        source = payload.get("source", "")
        filepath = payload.get("filepath", "")
        documents = payload.get("documents", [])

        if payload.get("answerable") and answer:
            # Show answer and source only
            self.answer_label.configure(text=answer)
            self.source_label.configure(text=f"📄 {source}  (Enter to open)" if source else "")
            self._documents = [{"filepath": filepath, "filename": source}] if filepath else []
            self.listbox.delete(0, tk.END)  # Hide document list when answer found
        else:
            # Show documents when no answer
            self.answer_label.configure(text="No direct answer found" if documents else "")
            self.source_label.configure(text="")
            self._documents = documents
            self.listbox.delete(0, tk.END)
            for doc in documents:
                self.listbox.insert(tk.END, f"📄 {doc.get('filename', '')}  —  {doc.get('preview', '')[:50]}")
            if documents:
                self.listbox.selection_set(0)

    def _clear(self) -> None:
        self.answer_label.configure(text="")
        self.source_label.configure(text="")
        self.listbox.delete(0, tk.END)
        self._documents = []

    def _select_prev(self, _) -> None:
        if not self._documents:
            return
        self._selected_index = max(0, self._selected_index - 1)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self._selected_index)

    def _select_next(self, _) -> None:
        if not self._documents:
            return
        self._selected_index = min(len(self._documents) - 1, self._selected_index + 1)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self._selected_index)

    def _open_selected(self, _) -> None:
        if not self._documents:
            return
        sel = self.listbox.curselection()
        idx = sel[0] if sel else self._selected_index
        if 0 <= idx < len(self._documents):
            filepath = self._documents[idx].get("filepath", "")
            if filepath:
                subprocess.run(["open", filepath], check=False)

    def run(self) -> None:
        self.root.mainloop()


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Launch the Synapse UI."""
    if CTK_AVAILABLE:
        print("Starting Synapse...")
        app = ModernSynapseUI()
    else:
        print("CustomTkinter not found, using fallback UI...")
        print("Install with: pip install customtkinter")
        app = FallbackSynapseUI()
    
    app.run()


if __name__ == "__main__":
    main()
