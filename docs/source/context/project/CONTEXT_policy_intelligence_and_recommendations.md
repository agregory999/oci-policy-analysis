# Project-Specific Context: Policy Intelligence Engine and Recommendations UI Integration

This document describes the contract and architecture that underpins how the policy analytics/engine layer and the unified UI recommendations tab work in the OCI Policy Analysis project. It is the canonical reference for how backend analytics, the overlay model, and UI subtabs are wired together—and for extending intelligence with new strategies.

---

## 1. Architecture & Overview

- **PolicyIntelligenceEngine** ([`logic/policy_intelligence.py`](../../../src/oci_policy_analysis/logic/policy_intelligence.py)):  
  The engine orchestrates all post-load analysis by dispatching to a set of modular, pluggable **intelligence strategies**. Each strategy implements a simple protocol, and is registered (see `intelligence_strategies/__init__.py`) with an explicit run order. After execution, results are merged into a uniform **overlay** object using canonical models.
- **Intelligence Strategies** ([`logic/intelligence_strategies/`](../../../src/oci_policy_analysis/logic/intelligence_strategies/)):  
  These are single-responsibility, protocol-driven Python classes implementing specific analyses—such as risk scoring, overlap checks, or cleanup detection. Strategies are completely decoupled from the engine and UI. Adding a new strategy is a matter of subclassing and registering.
- **PolicyIntelligence Overlay Model** ([`common/models.py`](../../../src/oci_policy_analysis/common/models.py)):  
  All analytics output is attached to a single overlay dictionary (see `PolicyIntelligence` TypedDict). Keys include: `risk_scores`, `overlaps`, `consolidations`, `cleanup_items`, `recommendations`, etc., each matching their analytics category and documented canonical shape.
- **Recommendations UI Tab** ([`ui/policy_recommendations_tab.py`](../../../src/oci_policy_analysis/ui/policy_recommendations_tab.py)):  
  A multi-subtab UI notebook that simply **renders the overlay**. Each subtab selects/filters/presents a specific overlay key or overlay-internal section. The UI never recomputes analytics itself—it responds to overlay updates and (re)loads by re-pulling from the model.

---

### 1A. Architecture Diagram

```mermaid
flowchart TD
    A[DataRepository]
    B[Engine]
    C[Strategy]
    D[Overlay]
    E[RecommendationsUI]
    A --> B
    B --> C
    C --> D
    D --> E
```

<!--
Legend:
- DataRepository = PolicyAnalysisRepository (all loaded OCI/IAM state)
- Engine = PolicyIntelligenceEngine (registers strategies and runs analytics)
- Strategy = any pluggable/registered intelligence strategy
- Overlay = PolicyIntelligence overlay (aggregated analytics/results)
- RecommendationsUI = Tab and subtabs in the unified UI, displaying overlay data
-->

---

## 2. Strategy/Overlay/UI Mapping

The following table reflects the default strategies as registered in the canonical run order (`logic/intelligence_strategies/__init__.py`):

| Order | Strategy Class (File)                        | Overlay Key                     | UI Subtab(s)              | Description                                  |
|-------|---------------------------------------------|---------------------------------|---------------------------|----------------------------------------------|
| 1     | RiskScoreStrategy (`risk.py`)               | `risk_scores`                   | Risk Overview (subtabs)   | Computes potential risk for statements       |
| 2     | OverlapStrategy (`overlap.py`)              | `overlaps`                      | Overlap Analysis          | Finds conflicts, supersessions among policy  |
| 3     | ConsolidationSuggestionStrategy (`consolidation_suggestion.py`) | `consolidations`     | Policy Consolidation        | Suggests policies/statements to be merged    |
| 4     | InvalidStatementsCheck (`cleanup_invalid.py`)| `cleanup_items['invalid_statements']` | Cleanup/Fix     | Flags invalid statements for fix             |
| 5     | UnusedGroupsCheck (`cleanup_unused_groups.py`)| `cleanup_items['unused_groups']`  | Cleanup/Fix          | Detects groups with zero members             |
| 6     | UnusedDynamicGroupsCheck (`cleanup_unused_dynamic_groups.py`)| `cleanup_items['unused_dynamic_groups']` | Cleanup/Fix | Finds dynamic groups not referenced          |
| 7     | StatementsTooOpenCheck (`cleanup_statements_too_open.py`)| `cleanup_items['statements_too_open']` | Cleanup/Fix | Identifies ‘manage all-resources’ grants     |
| 8     | AnyuserNoWhereCheck (`cleanup_anyuser_no_where.py`) | `cleanup_items['anyuser_no_where']` | Cleanup/Fix    | Finds ‘any-user’ statements w/o a WHERE      |
| 9     | OverallRecommendationStrategy (`recommendations.py`)| `recommendations`      | Summary Table (top)         | Aggregates actionable recommendations        |

- Additional strategies may be registered by extending the protocol and updating the registration list (see below).

---

## 3. Overlay Contract (Data Model)

All analytics are merged into a single overlay. The canonical structure is:

```python
class PolicyIntelligence(TypedDict, total=False):
    overlaps: list[dict]
    recommendations: list[dict]
    risk_scores: list[dict]
    consolidations: list[dict]
    cleanup_items: NotRequired[dict]
```
- See [`common/models.py`](../../../src/oci_policy_analysis/common/models.py) for detailed data model definitions (e.g., `RegularPolicyStatement`, `PolicyOverlap`).  
- Each strategy writes its results into a corresponding overlay key or subkey (conventionally documented inline in the TypedDict or strategy comments).

In addition to overlay structure, the intelligence layer now relies on a **canonical principal key format** shared with the simulation engine and certain UI tabs. See the next section.

---

## 4. Principal Key Semantics (Shared Between Intelligence, Simulation, and UI)

Several parts of the system need a stable way to refer to a *principal* (subject) that appears in policy statements. Rather than duplicating ad-hoc formats, the project defines a single, canonical **principal key** representation and a helper to compute it.

### 4.1 Canonical Format

The canonical principal key string has the form:

```text
{subject_type}:{domain}/{name}
``

Where:

- `subject_type` is the parsed `subject_type` from a `RegularPolicyStatement` (usually lower-case):
  - `user`, `group`, `dynamic-group`, `service`, `any-user`, `any-group`, etc.
- `domain` and `name` are normalized according to type-specific rules (see below).

The normalization rules implemented by
`PolicyIntelligenceEngine.calculate_principal_key(subject_type, domain, name)` are:

1. **User / Group / Dynamic Group**

   ```python
   subject_type in {"user", "group", "dynamic-group"}
   ```

   - If `domain` is falsy or equal to `"default"` (any casing), it is
     normalized to the literal string `"Default"` in the key.
   - Otherwise the trimmed domain string is used as-is.

   Examples:

   - `subject_type="group"`, `domain=None`, `name="Admins"` →
     `"group:Default/Admins"`
   - `subject_type="user"`, `domain="default"`, `name="anita"` →
     `"user:Default/anita"`
   - `subject_type="dynamic-group"`, `domain="MyIdcs"`, `name="DG1"` →
     `"dynamic-group:MyIdcs/DG1"`.

2. **Any-user / Any-group / Service**

   ```python
   subject_type in {"any-user", "any-group", "service"}
   ```

   - The domain component is always the literal string `"None"` in the
     principal key.
   - The `name` piece carries the semantic value, such as:
     - `"any-user"` for the any-user subject
     - `"any-group"` for the any-group subject
     - the concrete service name (e.g. `"objectstorage"`, `"compute"`) for
       a service principal.

   Examples:

   - Any-user: `"any-user:None/any-user"`
   - Any-group: `"any-group:None/any-group"`
   - Service principal: `"service:None/objectstorage"`.

3. **Other / Fallback Types**

   For unrecognized `subject_type` values (or future extensions that still
   follow the `{type}:{domain}/{name}` pattern), the helper preserves `domain`
   as provided (stringified) and uses `"None"` if it is missing.

4. **ID-based Subjects**

   For now, **ID-based principals** such as `group-id` and `dynamic-group-id`
   are deliberately kept in a compact form outside the
   `{type}:{domain}/{name}` family, for example:

   ```text
   group-id:ocid1.group.oc1..xyz
   dynamic-group-id:ocid1.dynamicgroup.oc1..xyz
   ```

   These ID-style keys are typically produced directly by UI surfaces (e.g.,
   Tag-based Access builder) and are not currently processed via
   `calculate_principal_key`.

### 4.2 Producers of Principal Keys

Principal keys are primarily produced in three places:

1. **PolicyIntelligenceEngine** (`logic/policy_intelligence.py`)

   - The helper:

     ```python
     PolicyIntelligenceEngine.calculate_principal_key(subject_type, domain, name)
     ```

     computes the canonical key.

   - `build_permissions_report()` uses this helper when it converts
     `(subject_type, subject_domain, subject_name)` into the permissions
     report's `subject_key`. This ensures that permissions-report subjects
     use the exact same key shape as the simulation engine and UI.

2. **PolicySimulationEngine** (`logic/simulation_engine.py`)

   - `_normalize_principal_key(principal_type, principal)` implements the
     same rules as `calculate_principal_key`, but in engine-local form. It is
     used to normalize UI/MCP inputs into a `principal_key` string.
   - `get_statements_for_context()` and
     `get_required_where_fields_for_context()` both call
     `_normalize_principal_key` and then pass the `principal_key` into
     `get_applicable_statements()`.
   - `_principal_key_to_policy_search_filter(principal_key)` parses the
     `{type}:{domain}/{name}` format and converts it to the repository
     filter structure (`exact_users`, `exact_groups`, `subject`, etc.).

3. **SimulationTab & TagBasedAccessTab** (`ui/simulation_tab.py`, `ui/tag_based_access_tab.py`)

   - **SimulationTab** constructs `principal_key` strings using the same
     normalization rules as `_normalize_principal_key` so that the value
     handed to `simulate_and_record` exactly matches what
     `get_statements_for_context` would produce.
   - **TagBasedAccessTab** derives builder principals from parsed
     statements. For structured subjects (`user`, `group`, `dynamic-group`,
     `service`), it calls

     ```python
     PolicyIntelligenceEngine.calculate_principal_key(ptype, domain, name)
     ```

     and stores the resulting principal key directly in the builder's
     `Principal` dropdown.
   - For ID-based subjects (`group-id`, `dynamic-group-id`), the tab uses
     compact forms like `"group-id:ocid1.group..."` directly, without
     introducing a synthetic domain.

### 4.3 Consumers of Principal Keys

Principal keys are consumed for:

- **Policy search & simulation**
  - `PolicySimulationEngine.get_applicable_statements(principal_key, effective_path)`
    parses the key with `_principal_key_to_policy_search_filter`, then calls
    `policy_repo.filter_policy_statements(...)`.
  - `simulate_and_record(principal_key, effective_path, ...)` records the
    `principal_key` inside the `simulation_trace["simulation_context"]` so
    history and exports can identify the simulated subject.

- **Permissions report and intelligence overlays**
  - `build_permissions_report()` uses the same key as the `subject_key` in
    its nested `report` structure.
  - Consolidation and overlap helpers that display principal information may
    still use the more human-readable `_principal_str(st)` helper; they do
    not currently rely on the canonical key for grouping.

- **UI surfaces**
  - Simulation history and debugger tabs can safely log or inspect
    `principal_key` values knowing that `Default` and `None` carry defined
    semantics for domain.
  - Tag-based Access builder presents the **raw principal key string** in the
    Principal dropdown, so expert users can see the exact canonical key that
    would be used if they later send the constructed statement into the
    Simulation tab.

### 4.4 Default Domain Semantics

The explicit domain markers `"Default"` and `"None"` are important:

- `"Default"` signals "tenancy default identity domain" (or equivalent),
  and is used for user/group/dynamic-group principals when no domain is
  specified in the parsed subject.
- `"None"` signals "no identity domain concept is applicable" and is
  used for any-user/any-group/service subjects.

This explicitness avoids ambiguity when round-tripping between parsed
statements, internal models, and UI displays, and it ensures that future
features (e.g., subject lists that are already lists of principal keys)
have a well-defined key space.

---

## 4. UI Subtab Mapping and Data Sources

Each subtab in the unified recommendations UI directly reflects an overlay key or subkey as follows:

- **Summary Table** (top):  
  Renders the contents of `overlay['recommendations']` (aggregated by `OverallRecommendationStrategy` plus limits logic from compartment analysis).
- **Risk Overview (Statement/Policy)**:  
  Draws from `overlay['risk_scores']` and policy statement metadata.
- **Overlap Analysis**:  
  Renders `overlay['overlaps']`.
- **Policy Consolidation**:  
  Uses `overlay['consolidations']`.
- **Cleanup / Fix**:  
  Aggregates all lists inside `overlay['cleanup_items']`.
    - Ignore/hide and “Show Previously Ignored” features use a persistent set of ignored item keys (see UI for per-tenancy state).
    - “Take Action” wires to the Recommendation Workbench (see below).
- **Limits**:  
  Compartment/boundary analysis is shown directly from compartment metadata and statement counts, not overlay.
- **Recommendation Workbench**:  
  Accumulates per-action CLI/UI steps, rollback, and history, appended whenever a subtabs's “Take Action” is used.

---

## 5. Extensibility (Add/Change an Intelligence Strategy)

**A. To Add a New Strategy:**

1. **Implement the Protocol**  
   Create a new Python class in `logic/intelligence_strategies/`, implementing the `IntelligenceStrategy` protocol (see `base.py`). For example:
   ```python
   from dataclasses import dataclass
   from oci_policy_analysis.logic.intelligence_strategies.base import IntelligenceStrategy
   from oci_policy_analysis.logic.data_repo import PolicyAnalysisRepository

   @dataclass(frozen=True)
   class MyNewStrategy:
       strategy_id: str = "my_new_check"
       display_name: str = "Custom Check"
       category: str = "cleanup"  # Or risk, overlap, etc.
       def run(self, repo: PolicyAnalysisRepository, overlay: dict, params: dict | None = None) -> None:
           # Compute whatever analytics desired
           results = ... # list of dicts, TypedDict, etc.
           overlay.setdefault("cleanup_items", {})[self.strategy_id] = results
   ```
2. **Register the Strategy**  
   Add your class to the return list in `get_default_intelligence_strategies()` in `logic/intelligence_strategies/__init__.py`, placing it appropriately in run order.
3. **Update Docs and UI**  
   a. Document the overlay key output by your strategy here, under the relevant section/list.  
   b. Modify the appropriate UI subtab in `policy_recommendations_tab.py` to present the new overlay result (if needed).

**B. Overlay and Model Contracts**  
- All analytic and remediation data passed from strategy to overlay to UI should use explicit Python types or TypedDicts as defined in `common/models.py`. This ensures UI and strategy code remain compatible and maintainable.

---

## 6. Workbench and "Take Action" Integration

- Each “Take Action” operation in a subtab (Cleanup/Fix, and future Risk/Overlap/Consolidation extensions) creates action items in the **Recommendation Workbench**.
- Workbench action entries must include source, description, CLI and rollback instructions, and can accrue history/audit data over time.  
- See `policy_recommendations_tab.py` for workbench API details and per-action semantics; all actions are per-session and cleared on reload.  
- A diagram for workbench action flow:

```mermaid
sequenceDiagram
    Participant User
    Participant UI_Tab as Recommendations UI Subtab
    Participant Workbench
    User->>UI_Tab: Selects row(s), clicks Take Action
    UI_Tab->>Workbench: Append actions (with CLI/UI/rollback)
    Workbench->>Workbench: Stores per-row audit/history
    User->>Workbench: Selects action, views scripts/history
    User->>UI_Tab: Clicks "Reload All" (policies reloaded/intelligence rerun)
    UI_Tab->>Workbench: Out-of-date actions removed/audited
```

---

## 7. Coupling and Boundaries

- **Engine/Strategy:**  All analytics are delegated to pluggable strategies using a protocol-defined contract, never hard-coded in the engine. Strategies know nothing of UI.
- **Overlay/UI:** The UI only renders overlay data; it never computes analytics itself, and triggers only overlay reload or recomputation through the engine.
- **Models:** All overlay structure and per-item analytics are explicitly type-checked using TypedDicts and docstrings in `common/models.py`.
- **Extensibility:** Adding a new analytic, check, or recommendation is entirely plug-and-play. If you extend the overlay or models, document all updates in this file and the linked sources above.

---

## 8. References & Cross-links

- **Engine:** [`src/oci_policy_analysis/logic/policy_intelligence.py`](../../../src/oci_policy_analysis/logic/policy_intelligence.py)
- **Strategies/Registry/Protocol:** [`src/oci_policy_analysis/logic/intelligence_strategies/`](../../../src/oci_policy_analysis/logic/intelligence_strategies/)
- **Overlay Data Models:** [`src/oci_policy_analysis/common/models.py`](../../../src/oci_policy_analysis/common/models.py)
- **Recommendations Tab UI:** [`src/oci_policy_analysis/ui/policy_recommendations_tab.py`](../../../src/oci_policy_analysis/ui/policy_recommendations_tab.py)
- **Consolidation Workbench (proposal/demo):** [`src/oci_policy_analysis/ui/consolidation_workbench_tab.py`](../../../src/oci_policy_analysis/ui/consolidation_workbench_tab.py)

---

**Summary:**  
This contract decouples the logic of analytics, extensibility, overlay modeling, and UI rendering—ensuring you can add, modify, or reason about any kind of policy intelligence or recommendation in a single place. Use this file as your reference for all future strategy or overlay-related updates.