# Limited Modes

OCI Policy Analysis has two separate limited modes. They solve different
problems and can be used independently:

- **Limited Compliance Loading** limits the data supplied to the analysis
  engine. It is selected by the contents of a CIS Compliance export.
- **Limited Web User** limits a browser user's access to a scoped subset of a
  fully loaded dataset. It is selected by an administrator-created web access
  profile.

Limited Compliance Loading does not grant or restrict a user's web access.
Limited Web User does not change which CIS artifacts were imported.

---

## Limited Compliance Loading

A CIS Compliance import can contain only compartments and policies. This is a
useful limited-data workflow when the question is policy placement,
consolidation, or policy-statement limit exposure and the analysis environment
must not receive an identity inventory.

### Required and optional CIS artifacts

The import requires these files:

- `raw_data_identity_compartments.csv`
- `raw_data_identity_policies.csv`

Identity and metadata artifacts are optional. Their presence enables the
corresponding workflows:

| Supplied artifact | Additional capability |
| --- | --- |
| groups and membership plus users | group membership, user resolution, permissions analysis, and simulation |
| dynamic groups | dynamic-group inventory and matching-rule analysis |
| defined-tag catalog | tag namespace and tag-based access metadata |
| compatible saved snapshots | historical comparison |

Policy statements still expose the named group or dynamic group subject. A
subject written as `Domain/Name` uses that named identity domain; a bare name
uses the `Default` domain. This supports policy and workload-principal filters
by subject name, but it does not assert membership or resolve users.

### What works with a policy-and-compartments-only import

- Policy Analysis, Policy Browser, and hierarchy-aware effective paths.
- Policy statement moves, supported consolidation strategies, and
  statement-limit investigation.
- Recommendations, Reports, and the placement recommendation for statements
  that are effective two or more levels below their policy compartment.
- Workload Principals and policy-derived group/dynamic-group name filtering.
- Condition Tester, Cross-Tenancy Analysis, and packaged reference-data
  lookups.

### What is intentionally unavailable

- User/group inventory and membership-based analysis.
- Dynamic-group inventory and matching-rule inspection when that artifact was
  not supplied.
- Permissions Analysis and Policy Simulation, which require principal
  resolution.
- Tag Namespaces when no defined-tag catalog was supplied.
- Historical comparison for a partial import without a compatible identity
  snapshot.

The desktop application displays a yellow partial-import banner and disables
the unavailable tabs. The web application displays the same capability summary,
grays unavailable navigation, and disables controls if an unavailable page is
opened directly. The completion log records the imported artifact counts and
capability set at `WARNING` level.

To enable an unavailable workflow, load a more complete CIS export or a live
tenancy/cache dataset that includes the required data. Loading a partial export
does not change OCI resources.

---

## Limited Web User

Limited Web User allows non-admin users to access a **strictly scoped** subset of
OCI Policy Analysis web data.

This page is user/admin-facing guidance (what it enables and how to use it).
For architecture and implementation context, see:

- [Limited mode maintainer context](https://github.com/agregory999/oci-policy-analysis/blob/main/context/project/CONTEXT_limited_mode.md)

---

### What Limited Web User Enables

Limited Mode provides:

- Scoped web access for non-admin users.
- Compartment-root-based visibility (root + descendants).
- Optional identity-domain allow-list scoping for IAM entity detail views.
- Server-enforced restrictions so API payload tampering cannot expand access.

It is designed for read-oriented scoped analysis, not full admin operations.

---

### Roles

### Admin

- Authenticates with runtime admin key.
- Can load/cache data and manage limited profiles.
- Can access full/admin web surfaces.

### Limited

- Authenticates with an activated limited runtime key tied to a profile.
- Can access only scoped analysis surfaces.
- Cannot use admin/load/cache surfaces.
- Can use simulation only when the limited profile uses
  `policy_scope_mode=include_relevant_ancestors`.

---

### Scope Model

Limited access is defined by the active limited profile:

- `compartment_root_paths` (one or more scoped roots)
- `policy_scope_mode`:
  - `strict_descendants`
  - `include_relevant_ancestors`
- `allowed_identity_domains` (IAM detail allow-list)

If `allowed_identity_domains` is empty:

- users/groups/dynamic-groups endpoints return empty results.

---

### Authentication and Session Behavior

On successful limited login, session state includes:

- `auth_mode = "limited"`
- `limited_key_hash`
- `limited_scope` (profile + scope metadata)

Limited keys are runtime-scoped:

- Admin activates/deactivates keys at runtime.
- Keys are not persisted as active across application restart.
- Limited key login is tenancy-bound (key/profile tenancy mismatch is rejected).

---

### What Limited Users Can Access

Limited users are routed to a simplified limited home experience and can use:

- Policy Analysis
- Users / Groups
- Dynamic Groups
- Resource Principals
- Policy Simulation (Scoped), only when
  `policy_scope_mode=include_relevant_ancestors`

---

### What Limited Users Cannot Access

Blocked for limited sessions:

- Admin utility and admin-only pages
- Data load/cache/index/admin route surfaces
- Simulation surfaces when profile mode is `strict_descendants`

Prospective statements are read-only for limited sessions:

- Limited users can view scoped prospective statements.
- Limited users cannot create/edit/replace/validate prospective statements.
- Prospective builder endpoints remain admin-only.

---

### Backend Enforcement (Important)

Scope enforcement is done on the server, not just in navigation/UI.

- Policy routes enforce compartment scoping.
- IAM entity routes enforce domain allow-list filtering.
- Simulation routes are additionally guarded by
  `_require_simulation_access` (`include_relevant_ancestors` required).
- Prospective read route (`GET /prospective/statements`) is scope-filtered for
  limited users.
- Prospective mutation routes remain admin-only.
- Out-of-scope broadening in crafted payloads is ignored/blocked.

---

### Admin Usage: Managing Limited Profiles

Admins manage limited profiles in the limited-management/admin utility surface.

Typical tasks:

1. Create/edit profile scope (label, compartment root, domains, mode).
2. Activate/generate runtime limited key.
3. Share key with limited user securely.
4. Deactivate key when no longer needed.

---

### Verification and Testing Notes

Route and behavior tests are implemented for limited-mode route handling,
including tenancy mismatch, blocked-route behavior, and empty-domain filtering.

Primary test file:

- `src/test/test_web_limited_mode_routes.py`
