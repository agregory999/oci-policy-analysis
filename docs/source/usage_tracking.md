# Usage tracking and Qt analytics

The Qt workbench publishes usage data by default. Existing
`usage_tracking_enabled: false` preferences remain disabled. Open **Overview &
settings → Usage tracking** to change the setting. The preference is shared with
the Tk and web interfaces; it is saved immediately. Turning it off discards
pending Qt usage data. A request already in flight cannot be recalled.

## Published data

Qt records application start/exit, fixed page/subview identifiers, successful or
failed data loads, report generation, recommendation refresh and historical
comparison, and completed simulation runs. Inventory counts are limited to
policies, statements, groups, users, dynamic groups and compartments. Embedded MCP
continues using the existing tracker integration for tool metadata.

Each run includes a random run ID, application version, OS/Python version,
timestamps, `interface: "qt"`, schema version, and the last six tenancy OCID
characters when known. The suffix is a coarse grouping identifier, not proof of
a unique tenancy or a count of people. Before any tenancy is loaded it is
unknown. Switching tenancies starts a separate document; operations do not carry
over. The first loaded tenancy is associated with the current startup run.

Qt does not publish policy text, names, full OCIDs, cache names, paths, filters,
prompts, credentials, or exception messages. The Qt service accepts only declared
page/subview and operation categories, source enums and numeric inventory counts.
These rules apply to the new Qt instrumentation; legacy interfaces retain their
existing event payloads. This is usage instrumentation rather than an audit log.

Uploads use the existing project write-only Object Storage PAR and object layout:

```text
events/YYYY/MM/DD/<suffix-or-unknown>/<random-run-id>.json
```

Override the write target with `OCI_POLICY_ANALYSIS_USAGE_PAR_URL`. Uploads run on
a serial background worker at orderly exit and tenancy changes, with a three-second
HTTP timeout per request. Publication is best-effort: failures are logged without
credentials, are not retried and never block a GUI action. The process waits for
queued shutdown work after its window closes. There is no disk spool; crashes,
forced termination and offline sessions can lose usage data. Setting the flag
back on begins a fresh run.

## Run the companion Qt viewer

Install the optional Qt dependency with `uv sync --extra qt --extra web --extra mcp`.
Launch from source:

```bash
.venv/bin/python -m oci_policy_analysis.analytics.qt --days 30
```

After package installation, the separate command is:

```bash
oci-policy-analysis-analytics --days 30
```

The existing native Qt executable also opens the companion window:

```text
oci-policy-analysis-qt --analytics --days 30
```

On Windows run that command from the extracted Qt distribution directory with
`oci-policy-analysis-qt.exe`. On macOS the executable is inside the app bundle at
`Contents/MacOS/oci-policy-analysis-qt`. Use `--days 0` for all history. No second
binary or extra runtime dependency is needed beyond the existing Qt bundle.
The legacy Tk viewer remains available through
`python -m oci_policy_analysis.analytics --days 30`.

Set `OCI_POLICY_ANALYSIS_ANALYTICS_PAR_URL` to a separate **read-only PAR with
object listing enabled**, or enter it into the viewer's masked field. Click
**Load bucket** to read. The URL stays in memory; the viewer never stores it in
settings, logs it, publishes usage, or writes bucket objects. Read access and
listing must be enabled separately when creating the PAR, as described in
[Oracle's PAR documentation](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/usingpreauthenticatedrequests.htm).

The viewer provides run and date filters, interface filtering, an unknown-tenancy
switch, search, raw JSON inspection and filtered JSON export. Tabs cover runs,
overview, daily activity, versions/runtime, tenancy suffixes, features/subviews,
operations, MCP tools, web traffic and AI activity. All tabs use the same filtered
cohort. Date bounds and daily activity use UTC run end dates, falling back to start
dates for legacy documents without an end time. This matches the writer’s
upload-day object layout, including overnight runs. Bucket selection first
narrows by object date. Expand the bucket date range to retrieve additional history.
**Open usage JSON** supports individual legacy documents and arrays exported by
the viewer. Local imports work without bucket credentials.

Bucket listing follows every `nextStartWith` page, with a repeated-marker guard,
and understands JSON arrays, `objects`/`items` containers and complete legacy
XML listings. Truncated XML is rejected visibly rather than presented as complete;
use an OCI native JSON listing endpoint for paginated data.
Failed listings are shown as failures rather than zero usage. Individual
unreadable or malformed records are skipped with visible counts. Canceling/closing
retains the reader until its current bounded HTTP requests finish.

## Compatibility and extension assessment

The original implementation already separated the writer, defensive read models,
pure aggregation functions and Tk presentation. It was extensible and portable at
the data layer, but Qt had no tracking lifecycle integration. Its documentation
also retained obsolete import paths and an old bundled read-PAR description;
current maintained code requires a runtime read/list URL.

This change preserves the existing document fields, event/operation arrays,
object-key layout, aggregators, Tk command and loader list-returning API. New
`schema_version: 1`, `interface` and document-level `tenancy_suffix` fields are
additive. Older readers ignore them. New readers accept documents without those
fields or without operations, label the interface `unknown`, and ignore unknown
future fields and malformed individual records. No bucket migration or rewrite
of old objects is required. Previously captured tenancy suffixes are still read
from object keys; old local JSON without a suffix is shown as unknown.

New operation types remain visible in the generic Operations tab; new payload
fields remain visible in run JSON. Specialized metrics can extend the shared
aggregators without modifying transport or either UI. Analytics package imports
are lazy, so Qt/model usage does not require or initialize Tk.

Review fixes include resetting operations on tenancy switches, flushing
operation-only runs, retaining events across repeated initialization before a
flush, starting a new run after a prior flush, sanitizing URL-bearing errors,
handling malformed event containers, pagination, and exposing partial-read counts.

Live bucket results and upload-PAR expiry are **not verified** by offline tests.
No analytics read/list URL was configured during implementation. Supply that URL
in the viewer to inspect the actual historical dataset. Do not use the app's
write-only PAR as the viewer credential. The existing write endpoint can be
rotated through its environment override if a live upload reports failure.
