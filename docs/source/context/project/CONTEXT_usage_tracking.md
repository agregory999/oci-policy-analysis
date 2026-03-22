##########################################################################
# CONTEXT: Anonymous Usage Tracking
##########################################################################

## Purpose

The OCI Policy Analysis UI includes an **anonymous usage tracking** feature that
is controlled entirely from local settings.

The goals are:

- Understand **which features and tabs are actually used** in the wild.
- Capture **high-level, non-personal metrics** about how the tool is used
  (e.g., which tabs are opened, very coarse tenancy grouping), without ever
  including policy text or identity details.
- Use this information to guide **feature improvements and performance tuning**.

The design is deliberately conservative:

- Tracking is controlled by a simple boolean setting
  (`usage_tracking_enabled` in the local settings file).
- Only **non‑personal, aggregate-style metrics** are collected.
- No policy text, usernames, email addresses, or resource OCIDs are sent.
- A **write‑only Pre‑Authenticated Request (PAR)** to Object Storage is used so
  the desktop tool cannot read back any tracking data.


## High‑Level Design

### Components

1. **`common/usage_tracking.py`**

   - Defines a small `UsageTracker` class that records events in memory during a
     single application run.
   - On demand, it can serialize all events into a single JSON **run document**
     and upload that document to an Object Storage bucket using a write‑only
     PAR URL.
   - All networking and serialization errors are **swallowed**; tracking is
     strictly best‑effort and must never affect the UI.

2. **`main.App` integration** (in `main.py`)

   - Loads settings from `~/.oci-policy-analysis/settings.json`.
   - If `"usage_tracking_enabled"` is **missing**, it is **defaulted to
     `True`** on first run and written back to the settings file.
   - Initializes the global `UsageTracker` instance based on the current
     settings via `init_usage_tracker(...)`.
   - Emits **app start** and **tab change** events when tracking is enabled.
   - On clean application exit, attempts a **single flush** so one run document
     is uploaded per session (best-effort only).
   - The bottom status bar indicates whether usage tracking is currently **On**
     or **Off**.


## Configuration & Settings

### Settings keys

A single setting is stored in `~/.oci-policy-analysis/settings.json` and
managed via `oci_policy_analysis.common.config`:

- `"usage_tracking_enabled": true | false`
  - Whether anonymous usage tracking should be active.
  - If this key is **absent** on startup, the application treats that as a
    first run and **defaults it to `true`**, then persists the key back to the
    settings file.

There is **no longer a startup opt-in dialog** for usage tracking. Users who
wish to disable tracking can do so by editing the settings file directly (a
dedicated Settings-tab toggle may be added in the future).


### PAR URL configuration

The tracking upload target is a **write‑only Object Storage PAR** owned by the
project author.

In `common/usage_tracking.py`:

```python
PAR_BASE_URL_DEFAULT = (
    'https://objectstorage.us-ashburn-1.oraclecloud.com/p/'
    'rLkvSya24knxp2fiI1q-iwKti7QCi1E__56peO3NFc51I_Qc91GcYZvIreVn8MgQ/'
    'n/idxhxzdpc23m/b/policy-analysis-tracking/o/'
)
```

This base URL can be overridden at runtime using the environment variable
`OCI_POLICY_ANALYSIS_USAGE_PAR_URL`. This allows the project owner to rotate or
change the bucket/PAR without rebuilding the application.


## What Is Collected

All collected data is **non‑personal** and geared toward feature usage and
scale characteristics.

### Run document structure

At flush time, one JSON object is created per app run:

```json
{
  "run_id": "8d0b876a-1955-4fd4-9d0d-0a6ba10df63f",
  "app_version": "4.4.0.dev2",
  "started_at": "2025-03-20T21:15:03.123Z",
  "ended_at": "2025-03-20T21:45:10.987Z",
  "os": "Darwin-23.4.0-arm64-arm-64bit",
  "python": "3.12.13",
  "events": [
    { "event_type": "app_start", "ts": "...", "payload": {...} },
    { "event_type": "tab_change", "ts": "...", "payload": {"tab_name": "PoliciesTab"} }
  ]
}
```

Each event is represented by a `UsageEvent` with fields:

- `event_type: str`
- `ts: str` – UTC timestamp (ISO‑8601)
- `payload: dict` – event‑specific information (see below)

The `run_id`, `app_version`, and `tenancy_suffix` are recorded at the
`UsageRunDocument` level and also encoded in the uploaded object name
(`events/YYYY/MM/DD/<tenancy_suffix_or_unknown>/<run_id>.json`). They are not
duplicated inside each individual event to keep the per‑event payload minimal.


### Event types currently emitted

- `"app_start"`
  - Emitted once when the main `App` finishes initialization and tracking is
    enabled.
  - Recorded near the end of `App.__init__`.

- `"tab_change"`
  - Emitted whenever the main `ttk.Notebook` selection changes.
  - Implemented in `App._on_tab_changed` in `main.py`.
  - Payload:
    - `tab_name: str` – the class name of the tab widget (e.g.,
      `"PoliciesTab"`, `"PolicyBrowserTab"`, `"UsersTab"`,
      `"SettingsTab"`, etc.).
  - This allows analysis of which tabs are seen/clicked most often across
    sessions.

Additional event types such as `"load_policies"` (with counts and source) are
still planned and can be wired in without affecting the core tracking
abstraction.


### What Is **Not** Collected

By design, the tracker **must not** collect:

- Usernames or email addresses
- Policy statement text
- Resource OCIDs or other detailed OCI identifiers (beyond the final 6
  characters of the tenancy OCID for coarse aggregation)
- Any free‑form text inputs from the user

Only counts, types, and structural usage information (e.g., which tabs are
used, whether cache vs. live data is used) are in scope.


## Upload Path and Object Layout

Uploads use the base PAR URL plus a constructed object key.

In `UsageTracker.flush()` the key is built as:

```text
events/YYYY/MM/DD/<tenancy_suffix_or_unknown>/<run_id>.json
```

For example:

```text
events/2025/03/20/9af3c2/8d0b876a-1955-4fd4-9d0d-0a6ba10df63f.json
```

If the tenancy OCID is not known, the suffix `unknown` is used instead of a
6‑character suffix.

The upload is done with an HTTP `PUT` via `urllib.request`.


## Control Flow in `main.App`

### 1. Tracker initialization

On `App.__init__`:

1. Settings are loaded from `~/.oci-policy-analysis/settings.json`.
2. If `"usage_tracking_enabled"` is **missing**, it is set to `True` and the
   updated settings are saved.
3. `init_usage_tracker(self.settings, __version__)` is called to create the
   global tracker if enabled.
4. An initial `app_start` event is recorded if the tracker exists.


### 2. Status bar indicator

`App.update_status_bar()` builds the existing policy data load status string and
then appends a tracking indicator:

- When data is loaded from tenancy / cache / CIS output, the status might look
  like:

  ```text
  Policy Data: Tenancy "Example" loaded at 2025-03-20 21:15 UTC | Tool Usage Tracking: On
  ```

- When no data is loaded:

  ```text
  Policy Data: (Not Loaded) | Tool Usage Tracking: Off
  ```

The indicator reflects the current value of `usage_tracking_enabled` in
settings.


### 3. Tab change tracking

`App._on_tab_changed` is bound to the main `ttk.Notebook` via:

```python
self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)
```

At each tab change, in addition to existing behavior (AI pane toggling,
Settings tab refresh), the tracker is consulted:

```python
tracker = get_usage_tracker()
if tracker is not None and selected_widget is not None:
    tab_name = type(selected_widget).__name__
    tracker.track('tab_change', tab_name=tab_name)
```

Because this uses the tab widget’s class name, the same tab will have a
consistent identifier across releases and runs.


## Failure Behavior & Safety

The tracking feature is designed to be **non‑intrusive**:

- If `usage_tracking_enabled` is `False`, all helpers effectively become
  no‑ops.
- Network errors (e.g., offline, invalid PAR, timeouts) during upload are
  caught, logged at DEBUG/INFO, and **never raised** to the UI.
- If the PAR URL or environment override is not configured, uploads are
  skipped and a small INFO message is logged.
- All interactions with the tracker in `main.py` are wrapped in `try/except`
  blocks to avoid impacting the primary app behavior.


## Extensibility

Future enhancements can add more event types without changing the public
contract:

- `load_policies` events for each load source with counts:
  - `load_source: tenancy | cache | json | compliance`
  - `counts: {policies, statements, groups, users, dynamic_groups, compartments}`
- `app_exit` or `flush` events when the application closes.
- Feature‑specific events such as "simulation_run" or "recommendations_viewed"
  (still constrained to non‑personal data).

Any new events must continue to respect the privacy guarantees described
above.
