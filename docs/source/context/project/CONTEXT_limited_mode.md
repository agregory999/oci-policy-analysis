# CONTEXT_limited_mode.md

# Limited Mode (Web) — Project Context

## Purpose

This context document captures the current design and implementation context for
**Limited Mode** in the web UI.

Primary goal: allow non-admin users to access a **strictly scoped subset** of
tenancy analysis data, while ensuring backend enforcement prevents data
disclosure through direct API payload tampering.

This is a project/context artifact (architecture + behavior + acceptance), not a
task-focused end-user quickstart.

---

## Problem Statement

Original web auth was effectively binary (authenticated vs not authenticated),
without explicit modeling for:

- role (`admin` vs `limited`)
- compartment scope
- identity-domain scope

This allowed authenticated users to reach broad data surfaces once tenancy data
was loaded.

Limited Mode introduces tenancy-bound limited keys and mandatory server-side
scoping to enforce least privilege.

---

## Business Rules (Current)

1. Limited profiles are **per tenancy**.
2. Limited users are scoped to a **compartment root path** (including descendants).
3. Limited users may have an allow-list of identity domains.
4. Empty allowed identity domains means **no IAM detail access**:
   - users / groups / dynamic groups should return empty sets.
5. Policy statement text may still contain principal names.
6. Limited users must not access admin/index/load/cache surfaces.
7. Simulation is available for limited users **only** when
   `policy_scope_mode=include_relevant_ancestors`.
8. Prospective statements are **view-only** for limited users:
   - no create/edit/replace/validate/builder access
   - only scoped prospective rows are visible

---

## Security Model

### Roles

- **Admin**
  - Authenticated with runtime admin key.
  - Can load/cache tenancy data, manage limited profiles, and use full surfaces.

- **Limited**
  - Authenticated using an activated limited key mapped to a profile.
  - Access restricted to scoped analysis pages.

### Session Contract (Target)

```json
{
  "authenticated": true,
  "auth_mode": "limited",
  "auth_key_fp": "...",
  "limited_scope": {
    "profile_id": "...",
    "tenancy_ocid": "ocid1.tenancy...",
    "compartment_root_paths": ["ROOT/Finance"],
    "policy_scope_mode": "strict_descendants",
    "allowed_identity_domains": ["Default", "CorpDomainA"]
  }
}
```

### Key Storage Rules

- Never persist plaintext limited keys.
- Persist key hash/fingerprint only (e.g., SHA-256).
- Newly generated key material is shown once at creation/activation time.

### Runtime Activation Lifecycle

Profile definitions may persist, but limited keys are runtime-scoped
credentials:

- Admin activates/generates limited keys during an admin session.
- Activated limited keys are valid only for current process runtime.
- Restart clears active limited keys by default.
- Admin must re-activate/re-generate after restart.

This mirrors runtime admin-key behavior and reduces long-lived credential
exposure.

### Phase-1 Operational Decisions

- Existing admin startup runtime key logging remains unchanged.
- Limited profile definitions persist under tenancy settings.
- Runtime activation state is non-persistent (inactive at startup).
- Admin utility controls include:
  - activate limited profile key
  - deactivate limited profile key
  - display active key material in admin utility view
- While profile key is active, scope criteria controls are read-only in UI.
- When inactive, scope criteria become editable.

---

## UX Requirements (First Pass)

### Admin Utility Surface (Limited Scope Management)

Admin-only page/section with at least:

- list limited profiles for current loaded tenancy
- create/edit profile label, compartment root, allowed identity domains
- activate/generate runtime limited key (display once)
- deactivate runtime key(s)
- enable/disable profile definition

Visibility rules:

- visible only to admin sessions
- hidden/blocked for limited sessions
- excluded from limited-mode navigation

### Limited Landing Experience

On limited login, route to a simplified landing card indicating:

- scoped-data banner
- tenancy context
- scoped compartment root (descendants included)
- allowed identity domains (or explicit none)
- full admin/simulation/full-data unavailable warning
- instruction to contact admins for broader scope

### Masthead

Display app version plus role badge:

- `Admin`
- `Limited`

### Navigation Restrictions

Limited sessions should only expose first-pass pages:

- Policy Analysis
- Dynamic Groups
- Users / Groups
- Resource Principals

Admin/index/load/cache links are hidden and backend-blocked.
Simulation is conditionally available only when
`policy_scope_mode=include_relevant_ancestors`.

---

## API Enforcement Strategy (Critical)

Enforcement is backend-side on every relevant route; UI hiding is not security.

### Core Predicates

For limited sessions, returned records must satisfy:

1. **Compartment predicate**: effective/policy path within scoped subtree.
2. **Domain predicate** (IAM detail only): entity domain in allow-list.

### First-Pass Route Matrix

| Route | Limited behavior |
|---|---|
| `POST /filter/policies` | Return statements only within scoped subtree |
| `POST /filter/policies/by-subjects` | Same compartment scoping; expansions remain scoped |
| `GET /entities/users` | Allowed domains only; empty if domain list empty |
| `GET /entities/groups` | Allowed domains only; empty if domain list empty |
| `GET /entities/dynamic-groups` | Allowed domains only; empty if domain list empty |
| Resource-principal analysis routes | Apply compartment subtree scoping |
| Admin/load/cache routes | Deny (403) for limited |
| `GET /simulation/context-options` | Allowed only when `policy_scope_mode=include_relevant_ancestors`; otherwise 403 |
| `POST /simulation/statements` | Same as above; compartment/domain scope enforced |
| `POST /simulation/variables` | Same as above |
| `POST /simulation/run` | Same as above; compartment/domain scope enforced |
| `GET /simulation/history*` | Same as above |
| `POST /simulation/prospective-preview` | Same as above; returns scoped prospective-only rows |
| `GET /prospective/statements` | Limited users: scoped read-only rows only |
| `/prospective/statements/validate\|replace` | Admin-only |
| `/prospective/builder/*` | Admin-only |

### Policy Visibility Mode

Limited profiles include policy visibility mode:

- `policy_scope_mode: "strict_descendants" | "include_relevant_ancestors"`

Semantics:

- `strict_descendants` (default)
  - include scoped root and descendants only
- `include_relevant_ancestors`
  - also include relevant ancestor-scope statements affecting scoped subtree

This applies to policy statement visibility only; IAM detail visibility remains
controlled by `allowed_identity_domains`.

### Anti-Tamper Requirement

If limited users craft broadened API payloads, backend must still:

- enforce scope
- ignore out-of-scope expansions
- return only scoped rows (or empty)

---

## Data Model (Limited Profiles)

### Legacy-style persisted shape

```json
{
  "limited_access_profiles": [
    {
      "profile_id": "uuid",
      "label": "Finance auditors",
      "enabled": true,
      "tenancy_ocid_hash": "sha256(...)",
      "compartment_root_path": "ROOT/Finance",
      "allowed_identity_domains": ["Default"],
      "key_hash": "sha256(limited_key)",
      "created_at": "ISO8601",
      "updated_at": "ISO8601"
    }
  ]
}
```

### Preferred tenancy-keyed persistence

```json
{
  "limited_access_by_tenancy": {
    "ocid1.tenancy.oc1..aaaa...": {
      "profiles": [
        {
          "profile_id": "uuid",
          "label": "Finance auditors",
          "enabled": true,
          "compartment_root_path": "ROOT/Finance",
          "policy_scope_mode": "strict_descendants",
          "allowed_identity_domains": ["Default"],
          "created_at": "ISO8601",
          "updated_at": "ISO8601"
        }
      ]
    }
  }
}
```

Notes:

- Persistence should be tenancy-keyed (tenancy OCID preferred).
- `tenancy_ocid_hash` protects against wrong-tenancy key usage.
- `allowed_identity_domains: []` is valid and means no IAM detail visibility.
- Runtime key activation state is non-persistent and references profile IDs.

---

## Implementation Phases

### Phase 1 (Current Scope)

1. Role-aware session model (`admin` / `limited`).
2. Limited profile CRUD backend + admin management page.
3. Limited login resolving profile + scope.
4. Server-side scope guards on first-pass endpoints.
5. Limited landing card + role badge + nav restrictions.
6. Hard blocks for admin/load/cache in limited mode.
7. Conditional simulation access for limited mode when
   `policy_scope_mode=include_relevant_ancestors`.
8. Prospective statements read-only visibility for limited mode across
   Policy Analysis and Simulation.

### Phase 2 (Future)

- Extended reporting under scope.
- Key expiration/rotation automation.

---

## Acceptance Criteria (Phase 1)

1. Admin can create limited profile (key, compartment root, domain allow-list).
2. Limited key login yields limited scoped session + landing experience.
3. Limited users cannot access admin/index/load/cache routes.
4. Limited users can access simulation routes only when
   `policy_scope_mode=include_relevant_ancestors`.
5. Limited users have no prospective mutation capabilities; scoped
   prospective visibility is read-only.
6. Policy/analysis outputs are scope-limited.
7. Empty domain allow-list produces zero IAM detail rows.
8. Crafted API payloads cannot reveal out-of-scope data.

---

## Test Checklist

- [ ] Create limited profile with non-root compartment + one allowed domain.
- [ ] Login with limited key; verify role badge + scope warning card.
- [ ] Verify allowed pages work; blocked pages return 403/redirect.
- [ ] Verify simulation is enabled only for `include_relevant_ancestors` profiles.
- [ ] Verify policy routes exclude statements above scope root.
- [ ] Verify users/groups/dynamic-groups restricted to allowed domains.
- [ ] Verify empty-domain profile returns empty IAM endpoint results.
- [ ] Verify limited users can only view (not edit/build/replace) prospective statements.
- [ ] Attempt API payload tampering; verify scoped-only outputs.

---

## Risks / Notes

- Scope filtering should be centralized to avoid route drift.
- UI should clearly signal that empty results may be scope-driven.
- Simulation is conditionally enabled; route guard drift would be a leak vector,
  so `_require_simulation_access` must remain the single enforcement gate.
