"""Minimal Tk consumer stub using the new service scaffolding.

This does not replace the existing main Tk app. It exists as a lightweight
proof-of-structure for the future refactor.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.services.load_service import LoadService


class SampleTkApp(tk.Tk):
    """Minimal Tk shell for testing the new service container."""

    def __init__(self, settings: dict[str, object]) -> None:
        super().__init__()
        self.title('OCI Policy Analysis (Sample Tk Consumer)')
        self.geometry('900x600')

        self.context = AppContext.from_settings(settings)
        self.load_service = LoadService(self.context)

        header = ttk.Label(self, text='Sample Tk Consumer (Scaffold)', font=('TkDefaultFont', 14, 'bold'))
        header.pack(pady=12)

        self.status_var = tk.StringVar(value='Ready (no data loaded)')
        ttk.Label(self, textvariable=self.status_var).pack(pady=6)

        ttk.Button(self, text='Load from Cache (placeholder)', command=self._load_cache).pack(pady=6)

    def _load_cache(self) -> None:
        caches = self.context.cache.get_available_cache(tenancy_name=None)
        if not caches:
            self.status_var.set('No caches found. Load a tenancy first to create one.')
            return
        cache_name = caches[0]
        result = self.load_service.load_from_cache(cache_name=cache_name)
        summary = result.summary or {}
        self.status_var.set(
            f'{result.message} | compartments={summary.get("compartments", 0)} policies={summary.get("policies", 0)}'
        )


def main() -> None:
    # Placeholder settings stub. Replace with config.load_settings once wiring is finalized.
    app = SampleTkApp(settings={})
    app.mainloop()


if __name__ == '__main__':
    main()
