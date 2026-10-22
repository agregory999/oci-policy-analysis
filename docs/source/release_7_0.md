# 7.0: what's changed and where to start

7.0 brings a shared analysis core, explicit policy corpora, and a **Qt desktop
preview** alongside the existing Tkinter desktop. This page is the curated
upgrade and navigation guide; the [generated release history](https://github.com/agregory999/oci-policy-analysis/blob/main/CHANGELOG.md)
records individual fixes and prereleases. Feature-branch installers are previews;
use the release assets and documentation for the version you actually run.

## Upgrade essentials

- **Tkinter remains available.** `oci-policy-analysis-ui` still starts Tkinter.
  Qt uses the separate optional `oci-policy-analysis-qt` command and `qt` extra.
  CLI, web and MCP command names are unchanged.
- **Python imports change.** The former `oci_policy_analysis.common`, `.logic`,
  and top-level `.web` compatibility packages are removed. Use
  `application.core`, `application.services`, and `presentation.web` respectively.
  For ASGI hosting use `oci_policy_analysis.presentation.web.main:app`.
  The [integration guide](core_integration.md) shows maintained imports and lifecycle.
- **Keep supported saved snapshots.** Combined caches remain `version: 2` with
  current writers using `schema_version: 3`. Corpora and other derived analysis
  are rebuilt after load; no blanket cache conversion or deletion is required.
  Updated analysis can produce different findings from the same saved input.
- **The old OCI Generative AI desktop backend is removed.** Saved AI settings are
  inert, and `AppContext.ai` is gone. Qt's optional assistants use independently
  installed and configured clients; see [assistant setup](qt_mcp_codex.md).

## Raw statements and corpora

A **raw statement** is source evidence: what a policy said, where it came from,
and any parsing/validation findings. Invalid or unresolved statements remain
available for inspection rather than disappearing from the loaded snapshot.

A **corpus** is the compiled view the tool builds from that snapshot for analysis.
The regular policy corpus relates understood grants to principals, compartment
paths, resource types and permissions, with links back to their source. It also
records exclusions and coverage limitations. The cross-tenancy corpus separately
relates Define aliases and Admit/Endorse evidence; missing counterpart policies
or aliases remain gaps, not assumed grants.

For example, a source statement granting a group access to buckets stays intact
in **Policy Browser**. **Policy Graph**, permissions and simulation can use the
compiled relationships and still lead back to that source and its conditions.
A graph edge or normalized grant does not prove an OCI request will succeed:
conditions, denies, unresolved identities, catalog coverage and missing data
still matter. Neither corpus is a separate persistent database or an
authoritative OCI policy engine. See the [architecture](architecture.md) for the
model and [integration lifecycle](core_integration.md#python-embedding) for rebuilding it.

## Start the Qt preview

Choose the Qt-labelled asset for your operating system on the
[Releases page](https://github.com/agregory999/oci-policy-analysis/releases), or run
from a source checkout:

```bash
uv sync --extra qt --extra web --extra mcp
uv run oci-policy-analysis-qt --sample
```

`--sample` uses fictional demonstration data. Omit it to start empty. On Windows,
extract the Qt onefile ZIP and run `oci-policy-analysis-qt-onefile.exe`. Tkinter
assets remain separate. See [Setup](setup.md) for access requirements and the
[Qt desktop guide](qt_desktop.md) for detailed controls.

## Qt navigation walkthrough

Start at **Overview & Settings**. Load live OCI data, a named cache, an exported
snapshot or CIS Compliance output, or try Sample data. Review timestamp, counts,
collection scope and warnings before interpreting results. Desktop live loading
supports OCI profiles (including session tokens) and Instance Principal;
Resource Principal belongs to hosted workloads.

Standard mode keeps the core inspection pages visible:

| Page | Start here when you want to… |
| --- | --- |
| Policy Inventory | Inspect policy objects, placement, statement counts, tags and policy-limit coverage |
| Policy Browser | Filter original statements, including invalid evidence, and inspect parsed fields and conditions |
| Policy Graph | Follow compiled direct grant relationships and inspect source evidence and exclusions |
| Users / Groups | Explore loaded identities, memberships and related policy statements |
| Dynamic Groups | Inspect matching rules and known policy references, including groups marked not in use |
| Resource Principals | Explore any-user/any-group, dynamic-group and OKE workload identity evidence and residual conditions |
| Cross-Tenancy | Inspect aliases, source statements, related Admit/Endorse evidence and unresolved relationships |
| Recommendations | Review findings; explicitly run full analysis when the current snapshot has only minimal enrichment |
| Tools | Run focused utilities and export reports; see below |

Right-click a statement and choose **Statement details** to open the shared
evidence drawer, including original text and raw JSON. Ordinary selection does
not open the drawer or modify OCI. A successful reload publishes a new snapshot;
a failed Qt reload leaves the previous displayed snapshot available.

### What Advanced mode adds

Enable **Advanced mode** on Overview & Settings to reveal:

| Page | Purpose |
| --- | --- |
| MCP & Assistant | Serve the loaded snapshot to MCP clients and optionally chat through embedded Codex or Claude Code |
| Tag-Based Policies | Inspect parsed tag predicates with their complete conditions and provenance |
| Permissions Analysis | Explore the effective-permission report prepared by Full enrichment |
| Prospective Statements | Draft and manage local what-if policy statements |
| Simulation | Analyze an explicit principal, operation, compartment and request context against selected evidence |
| Consolidation | Review consolidation proposals and their evidence before exporting a plan |
| Historical Comparison | Compare two retained snapshots without replacing the active analysis snapshot |

Advanced also reveals **Tools → Maintenance** and the live **Policy loading**
method selector. Changing experience mode changes visibility; it does not run
analysis, reload data or change OCI. Minimal enrichment does not prepare every
advanced result: use Full intelligence where a workflow requires it.
See [simulation](simulation.md), [consolidation](consolidation.md),
[recommendations](recommendations.md), and [tag-based analysis](tag_based.md).

### Tools and logs

**Tools → Reports** offers Policy Inventory, Effective Permissions, Policy
Supersession and explicit Full Policy Overlaps. Run a report, inspect its JSON,
Markdown or HTML, then export. Permissions and supersession have enrichment
prerequisites; Full Overlaps is an expensive explicit operation. See [Reports](reports.md).

**Condition Tester** explores conditions with supplied context; unknown inputs
remain limitations. **Logging** exposes component log settings and the live log
view. Advanced **Maintenance** exposes local maintenance utilities. Overview,
Tools and (in Advanced mode) Historical Comparison are available without a loaded
tenancy; data-dependent actions still require their inputs. Other navigation
pages require a successful load. See the [Qt desktop guide](qt_desktop.md) for
logging, load lifecycle and policy-limit controls.

## Assistants, hosting and automation

**MCP & Assistant** serves seven query-only tools over a fixed loaded snapshot.
Embedded **Codex** and **Claude Code** stream conversation in Qt. External
**Claude Desktop**, **ChatGPT Desktop** and **Codex Desktop** open separate apps;
configure their MCP connection in those apps. Set up each tool's login, billing
and model access first. Qt uses that existing setup. Connecting alone does not
start a model question; **Send** starts embedded usage.

The activity tab tracks dispatched MCP requests from external clients as well
as embedded assistants. Provider API traffic outside MCP is not visible there.
Stop the snapshot endpoint before reloading. See [Qt MCP and assistants](qt_mcp_codex.md)
for executable discovery, connection setup and lifecycle.

For a hosted service, deploy web/MCP on OCI Container Instances with Resource
Principal. For custom reports, embed the core in a Function or scheduled VM job.
The [integration guide](core_integration.md) compares these choices and describes
weekly dynamic-group review and retained snapshots for historical comparisons.
Scheduling, durable history retention and report delivery are supplied by your
integration.
