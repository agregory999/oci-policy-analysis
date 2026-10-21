##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# base_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import tkinter as tk
from tkinter import ttk


class BaseUITab(ttk.Frame):
    """Provide shared help, documentation-link, and timing behavior for UI tabs."""

    DOCROOT = 'https://agregory999.github.io/oci-policy-analysis'

    def create_doc_link_label(self, parent, text: str, url: str, **grid_kwargs) -> ttk.Label:
        """Create a styled label that opens a documentation URL when clicked."""

        link_label = ttk.Label(
            parent,
            text=text,
            foreground='#0645AD',
            cursor='hand2',
            font=('TkDefaultFont', 10, 'underline'),
        )

        # Bind click to open the URL using the shared open_link helper
        link_label.bind('<Button-1>', lambda _e: self.open_link(url))

        if grid_kwargs:
            link_label.grid(**grid_kwargs)

        return link_label

    def open_link(self, url: str):
        """
        Open a link in the user's web browser. If browser opening fails, display the URL in a messagebox.
        """
        import webbrowser

        try:
            opened = webbrowser.open_new_tab(url)
            if not opened:
                raise RuntimeError('webbrowser failed to open the link.')
        except Exception:
            import tkinter.messagebox

            tkinter.messagebox.showinfo('Open Link', f'Open this link in your browser:\n{url}')

    def __init__(self, parent, default_help_text='', page_help_link=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.default_help_text = default_help_text
        self.page_help_link = page_help_link

        self.page_help_frame = ttk.LabelFrame(self, text='Context Help')

        # Frame inside the page help for left/right (90/10) split
        self.page_help_inner_frame = tk.Frame(self.page_help_frame)
        self.page_help_inner_frame.pack(fill='both', expand=True, padx=5, pady=(5, 0), ipady=2)

        # Left: help text (90%), Right: optional permalink (10%)
        self.page_help_label = tk.Label(
            self.page_help_inner_frame, anchor='w', justify='left', wraplength=1100, height=2
        )
        self.page_help_label.pack(side='left', fill='both', expand=True)

        self.page_help_link_label = tk.Label(
            self.page_help_inner_frame,
            anchor='e',
            justify='right',
            fg='#0645AD',
            cursor='hand2',
            font=('TkDefaultFont', 11, 'underline'),
            wraplength=150,
            height=2,
            text='',
        )
        self.page_help_link_label.pack(side='right', fill='y')
        self.page_help_link_label.bind('<Button-1>', self._on_permalink_clicked)
        self._update_permalink_label()

        self.page_help_frame.pack(fill='x', padx=0, pady=0)
        self.set_page_help_text(self.default_help_text)
        self.show_help = True  # default, overridden by apply_settings

    def apply_settings(self, context_help: bool, font_size: str):
        """
        Apply application settings for context help and font size.

        Args:
            context_help (bool): Whether to show context (page) help.
            font_size (str): Font size as 'Small', 'Medium', etc.
        """
        self.show_help = context_help
        # Always remember the current font_size string for use in style logic
        sizes = {'Small': 9, 'Medium': 11, 'Large': 13, 'Extra Large': 15}
        self._current_font_size = sizes.get(font_size, 11)
        self.update_page_help_visibility()
        self.refresh_context_help()
        txt = self.page_help_label.cget('text')
        if context_help:
            if not txt or txt.strip() == '' or txt == '\n':
                self.set_page_help_text(self.default_help_text)
            else:
                self.set_page_help_text(txt)
        else:
            self.page_help_label.configure(text='')

    def set_page_help_text(self, text: str, temporary: bool = False):
        """
        Sets help label text, ensuring the area always shows (at least) 2 lines for layout stability.
        """
        # Force at least 2 lines (so the help area never shrinks). Pad with "\n" if necessary.
        lines = (text or '').splitlines()
        joined = '\n'.join(lines)
        if len(lines) < 2:
            joined += '\n'
        self.page_help_label.configure(text=joined)
        # Do not update right label (permalink) here! That is set by self.page_help_link.
        self._apply_page_help_style()

    def add_context_help(self, widget, message: str, restore_message: str | None = None):
        """
        Adds hover-based context help to given widget.
        If restore_message is not given, restores self.default_help_text.
        """

        def _show(_=None):
            self.set_page_help_text(message)

        def _restore(_=None):
            self.set_page_help_text(restore_message if restore_message is not None else self.default_help_text)

        widget.bind('<Enter>', _show)
        widget.bind('<Leave>', _restore)

    def set_page_help_permalink(self, permalink):
        """Set or change the persistent permalink in the Page Help area (right 10%)."""
        self.page_help_link = permalink
        self._update_permalink_label()

    def _update_permalink_label(self):
        """Internal: Update right label for permalink, shown always if page_help_link present."""
        if self.page_help_link and isinstance(self.page_help_link, str) and self.page_help_link.strip():
            disp = 'Tab Documentation'
            # If relative, prepend DOCROOT if starts with /
            link_url = self.page_help_link
            if link_url.startswith('/'):
                full_url = self.DOCROOT + link_url
            elif link_url.startswith('http:') or link_url.startswith('https:'):
                full_url = link_url
            else:
                # Fallback: treat as absolute
                full_url = link_url
            self.page_help_link_label.configure(
                text=disp, fg='#0645AD', cursor='hand2', font=('TkDefaultFont', 11, 'underline')
            )
            self.page_help_link_label.url = full_url
        else:
            self.page_help_link_label.configure(text='', fg='#0645AD', cursor='', font=('TkDefaultFont', 11))
            self.page_help_link_label.url = None

    def _on_permalink_clicked(self, event=None):
        """Open the link if present."""
        url = getattr(self.page_help_link_label, 'url', None)
        if url:
            self.open_link(url)

    def update_page_help_visibility(self):
        """
        Show/hide (and re-pin) the page help frame at the top of the tab.
        Always keeps help fixed before all other widgets—never at the bottom.
        """
        if getattr(self, 'show_help', True):
            self.page_help_frame.pack_forget()
            children = self.winfo_children()
            # Find first geometry-packed child other than self.page_help_frame
            pack_before = None
            for child in children:
                if child is self.page_help_frame:
                    continue
                try:
                    if child.winfo_manager() == 'pack':
                        pack_before = child
                        break
                except Exception:
                    continue
            # If another packed widget, insert page help before it, else use normal pack
            if pack_before is not None:
                self.page_help_frame.pack(fill='x', padx=10, pady=(10, 0), before=pack_before)
            else:
                self.page_help_frame.pack(fill='x', padx=10, pady=(10, 0))
        else:
            self.page_help_frame.pack_forget()

    def refresh_context_help(self):
        """
        Re-applies page help styles/colors after theme/font change or context visibility event.
        """
        self._apply_page_help_style()

    def _apply_page_help_style(self):
        """
        Applies consistent bg/font settings to the Page Help label/box.
        Attempts to match the ttk Theme background and update font size.
        """
        # Try to get the ttk theme background
        bg = None
        try:
            bg = ttk.Style().lookup('TLabel', 'background')
            if not bg:
                bg = ttk.Style().lookup('TFrame', 'background')
            if not bg:
                bg = self.page_help_frame.cget('bg')
        except Exception:
            bg = '#f0f0f0'
        # Use our stored _current_font_size (default 11 if not set)
        font_size = getattr(self, '_current_font_size', 11)
        self.page_help_frame.configure(style='Custom.TLabelframe')
        self.page_help_label.configure(bg=bg, font=('TkDefaultFont', font_size))
        self.page_help_inner_frame.configure(bg=bg)
        self.page_help_link_label.configure(
            bg=bg,
            font=('TkDefaultFont', font_size, 'underline' if self.page_help_link_label.cget('text') else 'normal'),
        )

    def timed_step(self, label, fn, *args, **kwargs):
        """Run a callable, log its elapsed time, and return its result."""
        import logging
        import time

        start = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - start

        # Choose logger: prefer self.logger if set, else fallback to base logger
        logger = getattr(self, 'logger', None)
        if logger is None:
            logger = logging.getLogger('oci-policy-analysis.ui.base_tab')

        always_log_timings = False
        if hasattr(self, 'app') and hasattr(self.app, 'settings'):
            always_log_timings = bool(self.app.settings.get('always_log_timings', False))

        # Use only the label in the message; module/class are conveyed by the logger name
        msg = f'[UI Timing] {label}: {elapsed:.2f}s'
        if always_log_timings:
            logger.critical(msg)
        else:
            logger.info(msg)
        return result
