# Context: Policy Intelligence Engine and Recommendations UI Integration

This file describes how the policy analytics/engine layer and the unified recommendations UI tab interact in the OCI Policy Analysis project. It serves as the source of truth for updating/expanding related features.

---

## 1. Overview

- **PolicyIntelligenceEngine (`logic/policy_intelligence.py`)**:  
  Performs all post-load analysis via **pluggable intelligence strategies** (risk, overlap, cleanup checks, consolidation suggestions, recommendations). The engine runs strategies in a fixed order and merges results into a single overlay. See **CONTEXT_intelligence_strategies.md** for the strategy protocol and how to add a new check.
- **PolicyRecommendationsTab (`ui/policy_recommendations_tab.py`)**:  
  Provides a unified UI notebook/tab for exploring analytics results—risk scores, overlaps, fix actions, and more—produced by the engine.

Together, they enable deep, actionable insight into Oracle Cloud policies, with a strong separation between analytics logic and its interactive presentation.

---

## 2. Data Flow and Integration

- After policy data is loaded, the **PolicyIntelligenceEngine** is initialized with a reference to the PolicyAnalysisRepository.
- The engine analyzes all policy statements and identity data, populating a single "overlay" structure (`self.overlay`, using the canonical PolicyIntelligence models).
- Overlay keys/results include:
  - `risk_scores`: Score, notes, and recommendations per statement (see **Risk scoring** below)
  - `overlaps`: Detected policy statement supersessions/conflicts
  - `consolidations`: Policies/statements that could be merged or simplified
  - `cleanup_items`: Actionable fix suggestions (invalid/inactive/overbroad)
  - `recommendations`: High-level actions for users (summarized from above)
- The **PolicyRecommendationsTab** fetches overlay data directly from the engine to populate:
  - **Summary Table** (top): Main recommendations (with priority, action)
  - **Sub-tabs**:
    - **Risk**: Scored statements, detailed notes, and suggested actions. Two reduction controls apply when computing scores: **WHERE clause risk reduction** (statements with conditions get a configurable % reduction) and **Service Principal risk reduction** (statements with subject type *service* and verb *use* or *manage* get a configurable % reduction, since service principals are inherently lower risk than group or dynamic-group for those verbs).
    - Overlap: Conflicts, superseding statements, and resources/compartments involved
    - Consolidation: Opportunities to combine policies/statements
    - Cleanup / Fix: Actionable fixes by type (invalid, unused, overly broad, etc.). **Ignore Selected** hides chosen items from the list (persisted per tenancy in consolidation state as `ignored_cleanup_keys`). **Show Previously Ignored** opens a dialog to re-show ignored items. **Take Action** sends selected items to the Recommendation Workbench. **Settings > Recommendation / Consolidation**: checkboxes let you enable/disable which **intelligence strategies** run (risk, overlap, each cleanup check, consolidation suggestions, recommendations); persisted as `enabled_intelligence_checks`. The engine’s `run_all(enabled_strategy_ids=...)` runs only the selected strategies.
    - **Recommendation Workbench**: Accumulated one-off actions (CLI/UI instructions, rollback, history, audit placeholder)
    - [Future]: For extending analytics/visualizations

---

## 3. Take Action and Recommendation Workbench

### 3.1 Concept

- Several subtabs (Cleanup/Fix, and in future Overlap, Consolidation, Risk) expose **Take Action** (or **Take Actions**) buttons. These are not full consolidation “plans”; they produce **one-off actions** that are appended to a shared **Recommendation Workbench**.
- Each time a user selects items and clicks **Take Action**, the UI:
  - Generates one or more **action items** (description, OCI CLI command, optional UI-based steps).
  - For each action, a **rollback** is defined as the logical opposite (e.g. “remove statement” → rollback “re-add statement”; “delete dynamic group” → rollback “re-create dynamic group” where feasible).
  - Appends these to the **Recommendation Workbench** subtab and switches the notebook to that subtab so the user can review, copy scripts, or reload to verify completion.

### 3.2 Recommendation Workbench Subtab (UI)

- **Layout** (aligned with Consolidation Proposal in the Consolidation Workbench):
  - **Actions table**: Columns such as #, Source (e.g. Cleanup/Fix), Type, Description, OCI CLI (or “See script”), Rollback CLI, Status, and a placeholder for **audit/history** per work item.
  - **Script / batch output**: When a row is selected, show the corresponding OCI CLI commands (or “UI-based steps”) in a read-only text area; optional format toggle (Execution vs Rollback vs Both).
  - **History and audit**: Each work item can carry a **history** (e.g. “Added 2025-02-17”; “Reload: still open” / “Resolved after reload”). A placeholder is reserved for future **audit data** (e.g. OCI Audit log links or timestamps).

- **Reload and completion**:
  - The top-level **Reload All** button (in Policy Intelligence) should **reload policies** (when data is from a live tenancy) and **re-run policy intelligence**. Thus:
    - Fixed issues (e.g. removed invalid statement, deleted unused group) **disappear** from the Cleanup/Fix tab after reload.
    - The workbench can track **per–work item history** (e.g. “Reload on &lt;date&gt;: issue still present” vs “Resolved”) for display in the table or a details pane.

### 3.3 First Implementation: Cleanup / Fix → Workbench

- **Cleanup / Fix** subtab: User selects one or more rows (invalid statements, unused groups, unused dynamic groups, overly broad statements, any-user without where) and clicks **Take Action**.
- For each selected item, the UI builds an action entry with:
  - **Source**: `Cleanup/Fix`
  - **Type**: Same as the cleanup type (e.g. Invalid Statement, Unused Dynamic Group).
  - **Description**: Short label (e.g. policy name + statement snippet, or group/dynamic group name).
  - **OCI CLI**: Command to perform the fix (e.g. remove statement from policy, delete dynamic group).
  - **Rollback**: Opposite command (e.g. add statement back, or “Re-create dynamic group manually” where CLI cannot restore).
- These entries are appended to the Recommendation Workbench table; the script area and history/audit placeholder are updated for the selected row.

### 3.4 Reload All Behavior

- **Reload All** (Policy Intelligence):
  - If the app has **reload_policies_and_compartments_and_update_cache** (e.g. live tenancy): call it so that policies/compartments are reloaded from OCI, cache is updated, and **all tabs** (including recommendations) are refreshed; the recommendations tab’s post-load path already re-runs policy intelligence, so analytics are recomputed and the Cleanup/Fix list reflects current state (fixed issues disappear).
  - If not (e.g. cache/compliance-only load): only **re-run policy intelligence** on the current dataset so that the summary and subtabs are refreshed without a full policy reload.

---

## 4. Extensibility and Feature Update Workflow

**To add/extend analytics or recommendations:**
- Document the new analytic or recommendation type here, under the appropriate overlay key or subtab heading.
- Implement computation and overlay population in `policy_intelligence.py` (`self.overlay[...]`).
- Update the corresponding subtab or summary table in `policy_recommendations_tab.py` to render the new analytic output, add controls, or expose new actions.
- (Optional) Update table layouts/column configs for new fields as needed.

**To add a new Take Action source (e.g. Overlap, Consolidation, Risk):**
- In the source subtab, ensure each row carries enough data (e.g. policy OCID, internal_id, resource identifiers) to generate CLI/UI instructions and rollback.
- When **Take Action** is clicked, build a list of workbench action dicts (source, type, description, cli_command, rollback_command, ui_instructions) and call the shared workbench append API so items appear in the Recommendation Workbench with history/audit placeholder.

**Examples of extensible areas:**
- Adding new category to `cleanup_items` (e.g., "statements missing comments")
- Adding a risk or exposure metric to `risk_scores` (see `calculate_potential_risk_scores` and the Risk tab dropdowns for WHERE clause and Service Principal reduction)
- Adding more Take Action buttons (Overlap: “remove superseded statement”; Consolidation: link to Consolidation Workbench or generate a single consolidation action)
- Persisting workbench actions to overlay/cache for session continuity
- Integrating OCI Audit data into the workbench audit placeholder

---

## 5. Coupling and Boundaries

- The analytics layer NEVER invokes UI directly; it only populates overlay data.
- The UI tab makes no analytic decisions—it simply renders the latest overlay analytic state and triggers recalculation on user reload/action.
- All shared structures (overlay keys, inner dict formats) are defined in typed models for both clarity and type safety.
- Recommendation Workbench state (list of actions, history) is owned by the UI; persistence (e.g. to overlay or a separate store) can be added later without changing the engine.

---

## 6. References

- Policy Intelligence Engine: [`src/oci_policy_analysis/logic/policy_intelligence.py`](../../../src/oci_policy_analysis/logic/policy_intelligence.py)
- Recommendations Tab UI: [`src/oci_policy_analysis/ui/policy_recommendations_tab.py`](../../../src/oci_policy_analysis/ui/policy_recommendations_tab.py)
- Consolidation Workbench (proposal subtab pattern): [`src/oci_policy_analysis/ui/consolidation_workbench_tab.py`](../../../src/oci_policy_analysis/ui/consolidation_workbench_tab.py)

---

**Summary:**  
All policy recommendations, advanced analysis, and clean-up opportunities are computed in the engine and delivered to the UI through a typed overlay structure. **Take Action** buttons on subtabs (starting with Cleanup/Fix) produce one-off actions that are collected in the **Recommendation Workbench** subtab, with OCI CLI/UI instructions, rollback, and a history/audit placeholder. **Reload All** reloads policies (when available) and re-runs policy intelligence so that fixed issues disappear and workbench history can reflect resolution. Additions or enhancements should start by updating this file, then implementing in the engine and UI.