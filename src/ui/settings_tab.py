import tkinter as tk
from pathlib import Path
from tkinter import ttk

from logic import config
from logic.caching import get_available_cache
from logic.logger import get_logger

logger = get_logger()


class SettingsTab(ttk.Frame):
    """Settings UI:
    - Display Options (theme + font size) in a LabelFrame
    - Toggle Bottom Pane button
    - (extend here with more settings later)
    """

    def __init__(self, parent, app, settings):
        super().__init__(parent)
        self.app = app
        self.settings = settings

        # Set the options from the saved settings
        self.tenancy_var = tk.StringVar(value=self.settings.get('tenancy_ocid', ''))
        self.profile_var = tk.StringVar(value=self.settings.get('named_profile', ''))
        self.recursive_var = tk.BooleanVar(value=self.settings.get('recursive', True))
        self.ip_var = tk.BooleanVar(value=self.settings.get('instance_principal', False))

        # Load profiles from ~/.oci/config
        self.profile_list = ['DEFAULT']
        try:
            # TODO - Check Env OCI_CLI_CONFIG_FILE
            with open(Path.home() / '.oci' / 'config') as fp:
                self.profile_list = [line[1:-2] for line in fp if line.startswith('[') and line.endswith(']\n')]
        except FileNotFoundError:
            logger.warning('OCI config file not found')
            self.profile_list = ['NONE']
            self.ip_var.set(True)

        # Display options (LabelFrame)
        disp = ttk.LabelFrame(self, text='Display Options')
        disp.pack(fill='x', padx=10, pady=10)

        # Theme
        ttk.Label(disp, text='Theme:').pack(side='left', padx=(8, 4))
        self.theme_var = tk.StringVar(value=self.settings.get('theme', self.app.style.theme_use()))
        theme_combo = ttk.Combobox(
            disp, textvariable=self.theme_var, values=sorted(self.app.style.theme_names()), state='readonly', width=16
        )
        theme_combo.pack(side='left', padx=(0, 10))
        theme_combo.bind('<<ComboboxSelected>>', lambda e: self.app.apply_theme(self.theme_var.get()))

        # Font size
        ttk.Label(disp, text='Font Size:').pack(side='left', padx=(8, 4))
        self.font_var = tk.StringVar(value=self.settings.get('font_size', 'Medium'))
        font_combo = ttk.Combobox(
            disp, textvariable=self.font_var, values=['Small', 'Medium', 'Large'], state='readonly', width=10
        )
        font_combo.pack(side='left')
        font_combo.bind('<<ComboboxSelected>>', lambda e: self.app.apply_font_size(self.font_var.get()))

        # Tenancy Config (LabelFrame)
        label_frm_tenancy_config = ttk.Labelframe(self, text='Tenancy and Config')
        label_frm_tenancy_config.pack(fill='x', padx=10, pady=10)

        # Instance Principal checkbox
        chk_instance_principal = ttk.Checkbutton(
            label_frm_tenancy_config,
            text='Instance Principal',
            variable=self.ip_var,
            # command=self._toggle_profile_dropdown,
        )
        chk_instance_principal.grid(row=0, column=0, padx=5, pady=5, sticky='w')

        # Recursion checkbox
        self.recursive_load = ttk.Checkbutton(
            label_frm_tenancy_config,
            text='Recursive',
            variable=self.recursive_var,
            # command=self._toggle_recursive_load,
        )
        self.recursive_load.grid(row=1, column=0, padx=5, pady=5, sticky='w')

        # Profile Selection
        self.label_profile = ttk.Label(label_frm_tenancy_config, text='Profile:')
        self.label_profile.grid(row=0, column=1, padx=5, pady=3)
        self.input_profile = ttk.OptionMenu(
            label_frm_tenancy_config, self.profile_var, self.profile_var.get(), *self.profile_list
        )
        self.input_profile.config(width=20)
        self.input_profile.grid(row=0, column=2, padx=5, pady=3)

        # Get available cached copies
        self.label_cache = ttk.Label(label_frm_tenancy_config, text='Cache:')
        self.label_cache.grid(row=1, column=1, padx=5, pady=3)
        self.cache_list = get_available_cache(None)
        self.cache_var = tk.StringVar(value=self.cache_list[0] if len(self.cache_list) > 0 else 'No Cache Available')
        self.cache_list_dropdown = ttk.OptionMenu(
            label_frm_tenancy_config, self.cache_var, self.cache_var.get(), *self.cache_list
        )
        self.cache_list_dropdown.config(width=20)
        self.cache_list_dropdown.grid(row=1, column=2, padx=5, pady=3)

        # Load button (lambda function with boolean for cache)
        ttk.Button(
            label_frm_tenancy_config, text='Load Tenancy', command=lambda: self._on_load_clicked(use_cache=False)
        ).grid(row=0, column=3, padx=5, pady=5, sticky='w')
        ttk.Button(
            label_frm_tenancy_config, text='Load Cache', command=lambda: self._on_load_clicked(use_cache=True)
        ).grid(row=1, column=3, padx=5, pady=5, sticky='w')

        # Progress indicator
        self.progress_var = tk.StringVar(value='')
        self.progress_label = ttk.Label(self, textvariable=self.progress_var, foreground='blue')
        self.progress_label.pack(anchor='w', padx=8, pady=(0, 10))

        # Bottom pane toggle
        ttk.Button(self, text='Toggle Bottom Pane', command=self.app.toggle_bottom).pack(pady=(6, 12))

        # (Optional) quick test button to push text to bottom entry
        ttk.Button(
            self,
            text='Put sample text in Bottom Entry',
            command=lambda: self.app.update_bottom_entry('Hello from Settings'),
        ).pack(pady=(0, 12))

    def _on_load_clicked(self, use_cache: bool):
        # Save current selections
        self.settings['tenancy_ocid'] = self.tenancy_var.get()
        self.settings['recursive'] = self.recursive_var.get()
        self.settings['instance_principal'] = self.ip_var.get()
        self.settings['named_profile'] = self.profile_var.get()

        # Save the settings now
        config.save_settings(self.settings)

        # Update indicator immediately
        self.progress_var.set('Loading tenancy…')

        # Kick off async call in main app
        self.app.load_tenancy_async(
            tenancy_id=self.tenancy_var.get(),
            recursive=self.recursive_var.get(),
            instance_principal=self.ip_var.get(),
            named_profile=self.profile_var.get() if not use_cache else None,
            named_cache=self.cache_var.get().replace('\n', '_') if use_cache else None,
            callback=self._on_load_finished,
        )

    def _on_load_finished(self, success: bool, message: str, clear: bool = False):
        """Callback from App once tenancy loading completes."""
        if success:
            self.progress_var.set(f'✅ {message}')
        else:
            self.progress_var.set(f'❌ {message}')

        # Schedule it to go away if clear was set
        if clear:
            self.after(2000, lambda: self.progress_var.set(''))
