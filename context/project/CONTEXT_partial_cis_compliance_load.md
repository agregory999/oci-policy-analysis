# Partial CIS Compliance Load Plan

## Status

Initial desktop implementation is complete and uncommitted on the feature branch.

Implemented:

- compartments + policies now load without identity-oriented CIS CSV artifacts;
- the repository records artifact counts and the capability set below, then logs both at `WARNING` when loading completes;
- policy-derived group/dynamic-group selectors retain their named domain or normalize an unqualified subject to `Default`;
- membership-dependent recommendation checks and unsupported consolidation strategies are skipped by declared capabilities;
- the desktop app shows a partial-load banner, disables unavailable tabs, and preserves Workload Principals filtering through policy-derived dynamic-group names; and
- focused regression coverage validates the minimum profile, a supported consolidation plan, unsupported strategy gating, inferred principal domains, and UI state.

Still deferred from the broader plan: cache-manifest persistence and an equivalent web dataset-status presentation.

Branch: `feature/partial-cis-compliance-load`  
Base: `v6.4.0` (`7469ec12`)

## Problem

Customers sometimes supply only CIS Compliance exports for compartments and policies. The current compliance loader requires identity-domain, dynamic-group, group-membership, and (normally) user CSV files before it loads policies. A missing identity file aborts the entire import.

That is unnecessarily restrictive for the primary use case: inspect policy-statement counts and hierarchy placement, identify policy moves that reduce policy-limit exposure, and generate consolidation/recommendation guidance. Those workflows do not require resolving a group or dynamic group to its members.

## Product intent

Accept a partial compliance dataset when it contains both required artifacts:

- `raw_data_identity_compartments.csv`
- `raw_data_identity_policies.csv`

Treat identity-oriented artifacts as optional. Preserve names and inferred domain information whenever a supplied policy statement contains a group or dynamic-group subject, even if a corresponding full identity inventory is absent. Domain inference is deterministic: use the named identity domain before `/`; when no domain prefix is present, use `Default`.

After import, show a persistent, dismissible-in-session banner that states:

1. the source is a partial CIS Compliance import;
2. which artifacts were loaded and their counts;
3. which analyses remain available; and
4. which principal-resolution workflows are unavailable and why.

The banner must make partial data feel intentionally supported, not like a degraded load that silently returned empty tables.

## Data capability model

Replace ad hoc source checks with one canonical capability snapshot derived at load time and persisted in caches.

Proposed capabilities:

```text
policy_statements
policy_objects
compartments
compartment_hierarchy
group_subject_names
dynamic_group_subject_names
groups_inventory
dynamic_groups_inventory
users_inventory
group_memberships
domains_inventory
defined_tag_catalog
principal_resolution
```

For the minimum partial profile, enable the first six capabilities. `group_subject_names` and `dynamic_group_subject_names` come from parsed policy statements, not from an asserted complete identity inventory. The UI must label these as policy-derived names and must not imply that all tenancy principals were loaded.

`principal_resolution` requires the relevant inventories and memberships. It must remain false for a policy-and-compartments-only import.

## Feature availability policy

### Available in the minimum partial profile

- Policy Inventory, Policy Analysis, statement search, policy-browser navigation, and compartment hierarchy views.
- Statement counts by policy and compartment, including limit-exposure analysis.
- Policy move/down-hierarchy planning and consolidation workbench operations that operate solely on statements, policies, and compartments.
- Policy-only recommendations, overlap/supersession analysis, and reports whose inputs are policy statements and compartment hierarchy only.
- Subject-name filtering when the group/dynamic-group name was parsed from a policy statement. Results mean “statements referring to this name,” not “effective access for this principal.”

### Available with warning or scoped output

- Recommendations and reports that mix policy-only and identity-dependent findings. Run supported recommendation strategies normally, without a special confidence label; skip only strategies whose inputs require unavailable user, group-membership, or identity-inventory capabilities.
- Workload-principal views remain available for policy-derived group/dynamic-group names, inferred domains, and parsed statement conditions. Do not show inventory completeness or membership-resolution assertions without source data.

### Disabled in the minimum partial profile

- Groups / Users membership and effective-access analysis.
- Dynamic-group inventory and matching-rule analysis when no dynamic-group artifact is supplied.
- Permissions Report and API Simulation paths that resolve a user, group membership, or effective principal.
- Tag-based analysis without a defined-tag catalog.
- Historical comparison unless both datasets expose compatible policy-and-compartment capabilities.

Each disabled action needs an explanatory affordance naming the missing artifact/capability and directing the user to load a fuller cache, tenancy data, or the relevant CIS output file.

## Import design

1. Introduce a structured `ComplianceLoadManifest`/capability result with discovered paths, loaded counts, missing optional artifacts, warnings, source type, and supported capabilities.
2. Change `PolicyAnalysisRepository.load_from_compliance_output_dir()` so compartments and policies remain required, while domains, dynamic groups, groups/memberships, users, and tag catalog are independent optional loaders.
3. Derive tenancy name/OCID from the compartments CSV. Fail with a precise error if neither can be established.
4. Maintain deterministic empty collections for omitted artifacts. Never use an empty collection to mean either “none exist” or “not loaded”; callers must use capabilities for that distinction.
5. Parse policy subjects to produce policy-derived named-group/dynamic-group selectors. Infer the domain from the identity-domain prefix before `/`, or use `Default` when absent. Preserve provenance so the UI can distinguish policy-derived selectors from loaded inventory records.
6. Run post-load intelligence in capability-aware mode. Policy-only strategies run normally; strategies declare their required capabilities and are skipped only when those capabilities are unavailable.
7. Persist the manifest and capabilities in the cache schema and expose them through desktop and web summaries.

## UI design

Add a shared dataset-status banner owned by the application shell/status area rather than duplicated in individual tabs.

Example message:

> Partial CIS Compliance dataset: loaded 42 compartments and 318 policies (1,942 statements). Policy hierarchy, statement moves, consolidation, and policy-only recommendations are available. User/group membership, effective-access, and principal-resolution features are unavailable because identity inventory artifacts were not supplied.

Tab-level behavior uses a shared capability gate. Where a tab can provide partial value, retain it with unavailable sections annotated. Where it cannot make a correct claim, disable its action before it runs. Keep the Workload Principals tab available for statement-derived principals and inferred domains, while gating membership/inventory-dependent operations within it.

## Code surfaces to investigate during implementation

- `application/core/repo/policy_analysis_repository.py` — current all-or-nothing CSV loader and source flags.
- `application/services/load_service.py` — load result and post-load orchestration.
- `main.py` and desktop status/UI refresh code — data-load banner lifecycle.
- Desktop tab refresh methods and web API summary endpoints — capability-aware display and action gates.
- `application/services/consolidation_workbench_service.py`, consolidation UI, reports service, recommendations service, and intelligence strategies — require each strategy to declare capabilities, then run only compatible strategies. In particular, grouping statements with the same permission set and location remains supported; current same-named-principal strategies should remain enabled when their only input is the policy-derived principal name/domain.
- Cache serialization/versioning — manifest persistence and backwards-compatible defaults.

## Test plan

1. Required artifacts only: compartments + policies imports successfully; hierarchy and statement counts are correct.
2. Each identity artifact omitted independently: import succeeds and corresponding capabilities remain false.
3. Missing compartments or policies: import fails with a precise missing-artifact message.
4. Policy-derived group/dynamic-group names: `/` domain prefix is retained, an absent prefix resolves to `Default`, and filtering locates matching statements without claiming membership resolution.
5. Workload Principals: statement-derived principal filtering works with inferred domains; membership-dependent controls remain unavailable.
6. Consolidation and statement-move planning: compatible strategies work from partial data and report policy/compartment provenance; incompatible strategies are skipped with a reason.
7. Recommendations/reports: compatible strategies render normally; only identity-dependent strategies/sections are omitted with a reason.
8. Desktop and web banners: accurately list loaded artifacts, capability availability, and disabled workflows.
9. Cache round trip: manifest/capabilities and banner state are retained.
10. Full CIS import and tenancy/cache loads: preserve existing behavior and expose complete capabilities.

## Settled decisions

- Keep Workload Principals available for policy-derived group/dynamic-group names and deterministic inferred domains; disable only membership/inventory-dependent operations.
- Infer a domain from the name segment before `/`; use `Default` when the subject has no domain prefix.
- Use a global partial-data banner and tab-local explanations for disabled actions.
- Present compatible recommendations normally, without a partial-data confidence label; skip only recommendation types that require user names or group membership.
- Make consolidation strategies capability-aware. Strategies that require only statements, permissions, locations, and policy-derived named principals remain eligible; strategies with unavailable inputs are skipped rather than disabling consolidation wholesale.
