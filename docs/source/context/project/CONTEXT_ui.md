# Project-Specific Context: User Interface (UI) Architecture & Tab System

This document describes the architecture, organization, patterns, and best practices for implementing the user interface of the OCI Policy Analysis tool. It is intended to be the canonical reference for developers working on UI features, designing new tabs, and extending the application.

---

## 1. Tab Structure and Organization

All UI (graphical interface) code is located under `src/oci_policy_analysis/ui/`. Each major tab or functional panel appears as its own module, named `<feature>_tab.py`. Example: `policies_tab.py`, `users_tab.py`, `cross_tenancy_tab.py`.

Tabs are registered and arranged in `main.py` (see the `App` class). Each tab is instantiated as a class (typically a subclass of `BaseUITab`) and added to the main application's `ttk.Notebook`, which manages the tabbed interface.

**Key notes:**
- Project tabs are created and referenced in a specific order for a consistent UX.
- New tabs must be imported and instantiated in the `App` class (`src/oci_policy_analysis/main.py`).
- Centralized settings and data models (repositories, engines) are passed to each tab on initialization.

---

## 2. The BaseUITab: Shared Functionality

Most tabs inherit from `BaseUITab` (`src/oci_policy_analysis/ui/base_tab.py`), which provides:
- **Unified Context Help**: Automatic insertion of a context help "help area" at the top of each tab, managed through `add_context_help(widget, message)` and propagated from global settings.
- **UI State and Settings Propagation**: All tabs receive changes to context help toggling, font size, style, and (if extended) theme from the main app via a central `apply_settings` interface.
- **Boilerplate Reduction**: Subclasses need only define which widgets need help; tab writers do not have to write per-widget Enter/Leave handlers or manual label setup.
- **Timing/Logging Hooks**: Tabs can leverage project-wide timing and logging infrastructure for load/refresh profiling (see `_post_load_update_ui` and tab refresh/load methods in `main.py`).

To ensure consistency, every tab that supports UI help should inherit from `BaseUITab` or implement an identical `apply_settings(context_help: bool, font_size: str)` method.

---

## 3. Tab Registration, Data Model/Engine Wiring, and Load Lifecycle

### How Tabs Are Created and Wired Up

- All main tabs are instantiated in the `App` class (`src/oci_policy_analysis/main.py`). Each receives proper references to shared data models, settings, caches, engines, and the parent notebook.
- Data models such as `PolicyAnalysisRepository`, `PolicySimulationEngine`, and others are also constructed centrally and passed to tabs as needed.
- This wiring allows for dependency injection, proper testing, and centralized state management.

**Example (simplified):**
```python
self.policies_tab = PoliciesTab(self.notebook, self, self.settings)
self.users_tab = UsersTab(self.notebook, self)
self.permissions_report_tab = PermissionsReportTab(self.notebook, self)
self.simulation_tab = SimulationTab(self.notebook, self, self.settings)
```
- All tabs are added to the main notebook using `self.notebook.add(<tab_instance>, text=<tab label>)`.

### Data/State Flow and Loading

- Data loading, data refresh, and status updates are handled centrally.
    - The application uses repositories (e.g., `PolicyAnalysisRepository`) and engines (`PolicyIntelligenceEngine`, `PolicySimulationEngine`). These are initialized at the application level and exposed to tabs on creation.
    - Upon data (or cache) load via various methods (tenancy, compliance output, JSON), special post-load update flows run: see `_post_load_update_ui` for UART-registered function calls.
    - Each tab exposes a set of update, refresh, or enable functions (e.g., `update_user_analysis_output`, `refresh_tree`, `enable_widgets_after_load`) which the application can call to propagate new data/UI states.
    - Central settings changes (context help, font size) are propagated live to all tabs via `App.refresh_all_tabs_settings()`, which in turn calls each tab's `apply_settings(...)`.

**Timing and Logging:**
- Timing for each post-load UI refresh or data push is logged for performance diagnostics.
- All tabs support rapid enable/disable and refresh cycles coordinated from the main App.

---

## 4. Tab Commonality, Data Models, and Engines

- **General Similarities:**
   - All tabs provide a consistent pattern for data updates, UI refresh, and state synchronization.
   - Tabs define or inherit an `apply_settings` method and one or more data refresh/update functions.

- **How Tabs Use Data Models and Engines:**
   - Key data engines/repositories are initialized in `App.__init__` (see `main.py`). For example:
       - `self.policy_compartment_analysis = PolicyAnalysisRepository()`
       - `self.simulation_engine = PolicySimulationEngine(...)`
       - `self.reference_data_repo = ReferenceDataRepo()`
       - `self.policy_intelligence = PolicyIntelligenceEngine(self.policy_compartment_analysis)`
     These are passed into relevant tabs on instantiation or accessed via the parent reference.

   - Tabs receive model/engine references as constructor arguments and use them for:
       - Data visualization/loading (`load_xxx_data`)
       - Engine-driven analytics (simulation, recommendations, report building)
       - Data caching and status display

   - On reload, the main App coordinates model/engine lifecycles, re-creates intelligence models as needed, and triggers each tab's update/refresh method.

- **Instantiation/Population:**
   - Tabs can be loaded/refreshed in bulk (see `App._post_load_update_ui`) or individually.
   - `apply_settings` is always called after load or settings update.
   - UI population is separated from data/model construction, ensuring consistent rerendering and minimizing state bugs.

---

## 5. Creating a New Tab: Best Practices

1. **Create the Module**
    - Name as `<feature>_tab.py` and place under `src/oci_policy_analysis/ui/`.
    - Inherit from `BaseUITab` if you want plug-and-play context help and unified settings propagation.
2. **Implement Required Interfaces**
    - Always implement `apply_settings(context_help: bool, font_size: str)`.
    - Define at least one update or refresh method (called by App after load/update).
    - Use `add_context_help(widget, message)` to wire up help for all user-interactive widgets.
3. **Register with the App**
    - Import your tab in `src/oci_policy_analysis/main.py`.
    - Instantiate in the App's `__init__`, passing required engines/data/settings.
    - Add it to the `self.notebook` with a descriptive label.
4. **Data/Model Usage**
    - Accept needed model/engine references in the constructor.
    - Use them for any backend queries, visualizations, or analytics.
    - Avoid loading or caching data in the tab directly; rely on the app-level repositories and engines.
5. **Context Help/Settings**
    - Always wire up your help and font logic to the tab's `apply_settings` for live updating.
    - Use the `default_help_text` option of `BaseUITab`.
    - Keep help tooltips short (2 lines max).
6. **Boilerplate/Update Patterns**
    - Place any necessary initialization, enable/disable, and data update calls as methods to be triggered by App.
    - See other tabs for standard patterns (e.g., `update_user_analysis_output`, `refresh_tree`).

---

## 6. Internal Lifecycles & Patterns

### Load and Refresh Events

- Central application lifecycle (load/refresh events, cache loads, data reloads) propagate through dedicated App methods, calling each tab's appropriate update method.
- Central settings (context help, font size, etc.) propagate via App, calling `apply_settings` on every tab for visual/layout consistency.
- To minimize race conditions and UI bugs, keep all data and settings flows coordinated by the main application and avoid direct cross-tab communication.

### Logging and Timing

- Tabs support application-wide logging for performance and debugging, with centralized log level control via settings.

---

## 7. Reference: Relevant Files

- `src/oci_policy_analysis/main.py`: App wiring, lifecycle, model/engine initialization, centralized tab management.
- `src/oci_policy_analysis/ui/base_tab.py`: Shared base tab implementation.
- `src/oci_policy_analysis/ui/`: All tab modules.
- Other `context/project/CONTEXT_*.md` files for individual tab details.

---

## 8. Summary

The UI layer of OCI Policy Analysis follows established architectural patterns for maintainability, consistency, and extensibility. Centralized tab management, unified settings propagation, and model/engine separation come together to provide a robust, predictable developer experience for UI extension and maintenance.

For further examples or boilerplate, study `main.py` and `src/oci_policy_analysis/ui/` tab source files directly.

---

## 9. Experimental Mode and Preview Tabs

Some UI features (such as the **Consolidation Workbench**) are considered experimental or preview-only. These are intentionally hidden behind an **undocumented CLI flag** so they can be iterated on without being part of the default, supported surface area.

### 9.1. How Experimental Mode is Enabled

Experimental features are toggled at process startup via a hidden command-line flag defined in `src/oci_policy_analysis/main.py`:

```bash
python -m oci_policy_analysis.main --experimental-features
```

Key points:

- `--experimental-features` is parsed by `argparse` but **suppressed from `--help` output** (using `help=argparse.SUPPRESS`).
- The parsed boolean is threaded into the main UI application:

  ```python
  app = App(force_debug=args.verbose, experimental_features=args.experimental_features)
  ```

- Within `App.__init__`, the flag is stored on the instance and used to gate construction of experimental UI components:

  ```python
  class App(tk.Tk):
      def __init__(self, force_debug: bool = False, experimental_features: bool = False):
          super().__init__()
          self.experimental_features = experimental_features
          ...
  ```

Developers should treat this flag as **internal-only**, intended for maintaining and validating experimental UI workbenches.

### 9.2. Consolidation Workbench Tab (Preview)

The Consolidation Workbench UI is wired into the project but is only instantiated when experimental mode is enabled.

- In `main.py`, the tab reference is created conditionally:

  ```python
  from oci_policy_analysis.ui.consolidation_workbench_tab import ConsolidationWorkbenchTab
  ...
  self.consolidation_tab = None
  if self.experimental_features:
      self.consolidation_tab = ConsolidationWorkbenchTab(self.notebook, self)
  ```

- When `experimental_features` is **False** (default):
  - `self.consolidation_tab` remains `None`.
  - No Consolidation tab is constructed, added to the notebook, or used in post-load update flows.

- When `experimental_features` is **True**:
  - `self.consolidation_tab` is instantiated.
  - The tab is surfaced as part of the **Advanced Tabs** control in the Settings tab.

The Settings tab’s “Show Advanced Tabs” toggle (`_toggle_advanced_tabs` in `settings_tab.py`) only operates on the Consolidation tab if it exists:

```python
advanced_tabs = [
    self.app.permissions_report_tab,
    self.app.condition_tester_tab,
    self.app.simulation_tab,
    self.app.policy_recommendations_tab,
]

# Only treat consolidation tab as advanced if experimental features are enabled
if getattr(self.app, 'consolidation_tab', None) is not None:
    advanced_tabs.append(self.app.consolidation_tab)

...

notebook.add(self.app.permissions_report_tab, text='Permissions Report\n(Advanced)')
notebook.add(self.app.condition_tester_tab, text='Condition Tester\n(Advanced)')
notebook.add(self.app.simulation_tab, text='API Simulation\n(Advanced)')
notebook.add(self.app.policy_recommendations_tab, text='Policy Recommendations\n(Preview)')
if getattr(self.app, 'consolidation_tab', None) is not None:
    notebook.add(self.app.consolidation_tab, text='Consolidation Workbench\n(Preview)')
```

This ensures the Consolidation Workbench follows the same advanced/preview pattern as other power-user tabs, but is only reachable when the experimental flag is enabled.

### 9.3. Status Bar Indicator for Experimental Mode

To make it clear when the UI is running with experimental behavior enabled, the fixed status bar at the bottom of the window is prefixed with an **Experimental Mode** marker when `experimental_features` is `True`.

In `App.update_status_bar` (in `main.py`):

```python
prefix = '**Experimental Mode**  -  ' if self.experimental_features else ''

if loaded:
    self.status_var.set(
        f"{prefix}Policy Data: {load_source} loaded at {ts_str}{reloaded_str}"
    )
else:
    self.status_var.set(f'{prefix}Policy Data: (Not Loaded)')
```

This prefix is **non-intrusive** (text only) but visually obvious for anyone debugging or testing experimental features.

### 9.4. Design Guidelines for New Experimental UI

When adding additional experimental tabs or UI features:

1. **Gate Construction**
   - Use the existing `experimental_features` flag on `App` to decide whether to construct the new UI component.
   - Do not reference experimental widgets in `apply_settings` or post-load flows unless they are present; use `getattr(..., None)` or explicit `is not None` checks.

2. **Surface via Advanced Controls**
   - Prefer surfacing experimental tabs through existing “Advanced” mechanisms (e.g., the Advanced Tabs toggle in `SettingsTab`) rather than always-on tabs.

3. **Avoid Public Documentation**
   - Do not add the experimental flag or features to end-user documentation or CLI help.
   - Internal context docs (such as this `CONTEXT_ui.md`) are the appropriate place to describe how experimental mode works for developers.

4. **Keep Behavior Reversible**
   - Experimental code paths should be easy to disable entirely by removing the gating logic and any references to the feature, without impacting the rest of the UI.

Following this pattern keeps the production UI stable while still allowing rapid iteration on new ideas behind an explicit, opt-in experimental switch.