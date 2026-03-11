# Context: User Interface (UI) Architecture & Tab System

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