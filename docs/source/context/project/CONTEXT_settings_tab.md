# Project-Specific Context: Settings Tab

The Settings tab centralizes all project configuration for OCI Policy Analysis, including environment details, cache controls, GenAI features, and import/export of tenancy data.

---

## 1. Main Setting Categories and Options

### A. Tenancy and Connection
- **Tenancy OCID**: Specify the tenancy to analyze.
- **Instance Principal**: Checkbox to enable/disable IAM instance principal authentication.
- **Recursive**: Loads all compartments/subcompartments if checked.
- **Profile**: Choose named CLI profile (from ~/.oci/config); disabled if OCI config not found.
- **Session Token**: Entry & load button for use with ephemeral session tokens.
- **Compartment for GenAI**: Used when testing GenAI/AI features.

### B. Display and UI Controls
- **Font Size**: Small, Medium, Large, Extra Large; controls UI font.
- **Toggles**: Show/hide Console & Debug Tab, Maintenance Tab, Advanced Tabs (those for admin or advanced roles).
- **Context Help (Page Help)**: If enabled, context-sensitive Page Help frames are shown at the top of supported tabs (e.g., Policies). These provide guidance relevant to each section of the app. When unchecked, Page Help is instantly hidden. Page Help adapts to your theme and font size settings for consistent appearance.

### C. Embedded MCP Server Options
- **Host/Port**: Configurable, autosaves on change. Host defaults to 127.0.0.1, port to 8765 unless otherwise set.

### D. Cache Management
- **Cache List**: Shows available local tenancy data caches.
- **Load from Cache**: Reloads the UI with cached tenancy data as selected.
- **Refresh Caches**: Cache dropdown is refreshed automatically after load/import operations.

### E. GenAI / Model Configuration
- **Regional Endpoint**: Service endpoint for OCI GenAI API.
- **Compartment OCID**: Target for GenAI queries.
- **Select Model**: Table of available models, selection updates current model OCID.
- **Apply & Test**: Updates and validates GenAI settings; disables/enables AI UI.

---

## 5. Page Help / Context Help

When **Context Help** is enabled in Display Options, a "Page Help" area is dynamically shown at the top of certain tabs (such as the Policies tab). This label frame provides contextual guidance and best-practices for the current section. Disabling Context Help instantly hides the help.

- Help text is optimized for each tab.
- Page Help's appearance (background color, font size) matches your global style settings for a seamless UI experience.
- The Context Help setting is saved and restored across sessions.
- More tabs may support Page Help over time as the app evolves.

---

## 2. Data Import, Export, and Load

- **Load from Tenancy**: Fetches fresh data from OCI, using current profile/config options.
- **Load from Cache**: Loads a selected cached dataset; improves performance/offline access.
- **Import JSON (share/backup)**: Imports tenancy data from standardized JSON file, supporting backups or transfers.
- **Export JSON (share/backup)**: Exports current tenancy data cache to JSON for external use or backup.
- **Load from Compliance Output Data**: Import findings from regulatory/compliance scans if directory is provided.

- Buttons/actions display in the "Tenancy and Config" section with corresponding UI elements for each option.
- Progress is shown using a **single modal popup workflow** for load/import operations (tenancy, cache, compliance output, and JSON import).
- The popup uses staged messages (for example: loading source data, running policy intelligence, populating tab data, updating status bar, and final done/summary).
- The previous right-side inline load status area in Settings is intentionally removed to avoid duplicate progress channels.
- The fixed bottom status bar remains the canonical loaded-state indicator (data source/timestamps/tracking flag).

---

## 3. Additional Features and Notes

- **Autosave**: MCP host and port are saved automatically when modified.
- **Error Handling**: UI warns for invalid ports or config issues.
- **Toggle Console/Maintenance/Advanced Tabs**: Lets users reveal or hide extra/debugging tabs as needed.
- **Refresh Cache List**: Manually update the cache dropdown after reload or import operations.

---

## 4. Code Location

Implementation: [`src/oci_policy_analysis/presentation/desktop/settings_tab.py`](../../../src/oci_policy_analysis/presentation/desktop/settings_tab.py)

---

Settings tab design supports flexible project deployment, quick environment reconfiguration, robust caching, and easy backup/share of tenancy analysis state.