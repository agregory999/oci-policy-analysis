# Project-Specific Context: User Interface (UI) Layer

This document details design decisions, history, and guidance for UI (tab/screen) implementation in this repository. It helps ensure all new user-visible features align with established project conventions and quality standards.

---

## 5. Page Help / Contextual Help Pattern

**Overview:**  
The Page Help ("Context Help") pattern provides instructional text at the top of any tab or UI page, which dynamically updates to reflect the user's current focus/hover area.

**Current Implementation (2026-01):**

- **Unified settings propagation:** All user-facing tab features (context help, font size, theme, future interactive UI settings) are coordinated from main.py, using one central method (`refresh_all_tabs_settings`). This is invoked whenever a relevant setting or state changes, so the App orchestrates global consistency across all tabs.
- *All tabs* that support context help either inherit from `BaseUITab` (see `src/oci_policy_analysis/ui/base_tab.py`), or implement the same interface.
- Every tab must provide an `apply_settings(context_help: bool, font_size: str)` method, which is called centrally by main.py. This ensures tabs are always in sync with global settings.
- BaseUITab provides:
  - Automatic creation and management of the help area as a `LabelFrame` at the top.
  - The `add_context_help(widget, message)` API for one-liner help wiring for any widget (Label, Entry, Checkbutton, Combobox...)
  - Synchronization with the universal Context Help toggle: when context help is disabled (via Settings), the page help box disappears from all tabs live.
  - Styling, font size, and theme background are updated consistently on tab creation and when global settings change.
  - When the Context Help setting is **turned on** at runtime, the default help text *always* appears instantly without requiring mouse movement.
  - When the font size is changed globally, the help area's text and appearance updates immediately, with no user interaction required.
  - Tab writers *do not* need to manually bind `<Enter>/<Leave>` for every widget—one helper method call suffices.
- Specialized non-BaseUITab tabs must ensure their apply_settings always triggers the default help text when context help is enabled and the help label is empty, otherwise the help label may be blank after toggling.
- Help text must always fit within two lines for clarity.

**Pattern Example (as of BaseUITab):**
```python
class MyTab(BaseUITab):
    def __init__(self, parent, ...):
        super().__init__(parent, default_help_text="Default help for tab area.")
        ...
        my_button = ttk.Button(...)
        self.add_context_help(my_button, "Button does XYZ. (Limit: 2 lines)")
        combo = ttk.Combobox(...)
        self.add_context_help(combo, "Choose a value for xyz.\nImpacts policy display below.")
```
*No need for manual page_help_frame setup or event handler boilerplate.*

**Best practices for extending tabs:**
- Each tab should define an `apply_settings(context_help: bool, font_size: str)` method, which is always called by main.py/App every time relevant settings change. All visual/interactive UI updates must be driven from this interface for consistency.
- Use BaseUITab as a base for all tabs that want context help. Tabs with custom needs (or that cannot inherit BaseUITab) must still fully implement the same apply_settings interface.
- Use the `default_help_text` parameter in the base class to set initial help for the tab. This default help is guaranteed to show immediately after toggling context help ON, even if no mouse movement has yet occurred.
- For each high-level area, use one call to `add_context_help`. Avoid recursive child widget bindings.
- All widget-specific help should fit within two lines for scanability.
- On any global context help toggle or font size change, tabs' apply_settings method (from BaseUITab or equivalent) must show, style, and populate the help label immediately. Users should never need to interact for the help area to appear or update.
- When the global context help setting is toggled (or other propagated setting changes), tabs use their `apply_settings` interface to update themselves, under the full control of main.py/App as orchestrator.
**Historical Note:**
Previous versions used per-tab copies of help-area setup, individual event handlers, and manual show/hide logic. As of 2026, all new and refactored tabs use BaseUITab and the unified context help system.

**Project Guidance:**  
- Do not reimplement page_help_frame, set_page_help_text, or similar per-tab unless making a specialized composite panel.
- Contribute new help best practices and working code to BaseUITab so all tabs benefit.

**See code:**
- `src/oci_policy_analysis/ui/base_tab.py` (BaseUITab)
- Example usage: `settings_tab.py`, `policies_tab.py`, etc.

**Further Reading:**  
See project’s `settings_tab.py`, `main.py`, `policies_tab.py` for full working examples and code comments. For advanced event handling/focus tracking, see GUI community patterns for context-aware hints and generic event handlers.

---

## 1. Area Overview

The UI layer consists of tabbed views found in `src/oci_policy_analysis/ui/`. Each tab (e.g., resource principals, policies, dynamic groups, etc.) is a discrete module following the repository’s overall UI patterns.

---

## 1a. UI Area Context Files

This document provides the overall UI strategy. Each major functional area/tab is documented in a dedicated context file. If comprehensive context for a tab does not yet exist, the filename is listed as a placeholder (to be created).

- [Policies Tab](CONTEXT_policies_tab.md) (to be created: describes table display, sorting, and filtering)
- [Cross Tenancy Tab](CONTEXT_cross_tenancy.md)
- [Simulation Tab](CONTEXT_simulation_engine.md)
- Resource Principals Tab: _see_ CONTEXT_resource_principals_tab.md _(TBD)_
- Dynamic Group Tab: _see_ CONTEXT_dynamic_group_tab.md _(TBD)_
- Policy Recommendations Tab: _see_ CONTEXT_policy_recommendations_tab.md _(TBD)_
- Permissions Report Tab: _see_ CONTEXT_permissions_report_tab.md _(TBD)_
- Historical Tab: _see_ CONTEXT_historical_tab.md _(TBD)_
- Users Tab: _see_ CONTEXT_users_tab.md _(TBD)_

Add or update individual tab context files as features evolve.

## 2. Evolution Timeline and Major Changes

| Date      | Commit Hash | Change Summary                        | UI Modules Impacted                  |
|-----------|-------------|---------------------------------------|--------------------------------------|
| 2026-01-08 | a2ae328d    | Major update: Merge Policy Intelligence, redesign tabs | resource_principals_tab.py, policy_overlap_tab.py, ... |
| ...       | ...         | ...                                   | ...                                  |

_(Populate this table over time with notable UI/UX history for reference.)_

---

## 3. Project-Specific UI Rules

- New tabs/modules must use `X_tab.py` suffix and be placed under `ui/`
- Tabs should be registered in the main UI controller for discoverability
- Follow naming and structural conventions as outlined in project’s UI codebase (see current open tabs for examples)
- UI docstrings must explain feature intent, entry points, and input/output specs

---

## 4. Exceptions and Customization

- When project UI patterns conflict with the [GENERIC_UI_GUIDELINES.md](../generic/GENERIC_UI_GUIDELINES.md), this file takes precedence for this repository.
- Design system elements (colors, icons, layout) adhere to project’s baseline—update this section if a refactor occurs.

---

For foundational UI theory and workflow, start with [../generic/GENERIC_UI_GUIDELINES.md](../generic/GENERIC_UI_GUIDELINES.md).
