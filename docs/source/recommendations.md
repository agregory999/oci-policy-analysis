# Recommendations

The **Recommendations** tab is the central UI for reviewing, understanding, and acting on security, cleanup, and optimization findings within your OCI tenancy. This tab synthesizes actionable insights from a pluggable, analytics-driven engine and presents them in an interactive, user-friendly dashboard.

---

## How Does It Work?

Recommendations and related findings are **dynamically generated** by the Policy Intelligence engine, which evaluates your loaded policies, users, groups, and compartments against a suite of pluggable analytic strategies. These strategies identify risky, invalid, redundant, or overlapping policy statements and aggregate results into a unified model.

**Key highlights:**
- Every section of this tab draws from live analytics and data overlays—there is no static "rules table."
- Intelligence strategies can be extended and updated without changing the UI or needing a redeploy.
- You don't need to interpret raw OCI policy text; instead, you get guided, actionable recommendations and insight into why they're being surfaced.

If you're interested in all the fine details—how the engine works, how plug-ins (strategies) are added, and what happens under the hood—see **Further Reading: AI Context** at the end of this guide.

---

## Navigating the Recommendations Tab

The Recommendations tab is organized into several subtabs and panels, each focused on a major area of IAM analytic findings:

> **Web flow note:** In web mode, this experience is available through the Recommendations page and related workbench pages. Some actions are intentionally simplified compared to desktop, but the core analytics model (risk, overlap, consolidation, cleanup/fix, limits, and workbench tracking) is shared.

### 1. **Summary Table**
- **Purpose**: The first thing you see—a high-level list of the most important, prioritized recommendations (critical risks, urgent cleanups, consolidation opportunities, and policy statement limit alerts).
- **Tips**: Each row summarizes an actionable item. Use **Reload All** in **Cleanup In Progress** to refresh live IAM and policy data and rerun intelligence.

---

### 2. **Risk Overview**
#### a. *Policy Risk*
- **Purpose**: Shows aggregate risk scores for each policy, giving you a sense of where your riskiest or most permissive policies live.
- **Features**:
  - Filter by WHERE clause/service-principal reduction (adjusts scoring).
  - Sort and drill down into risk summaries.
  - See example high-risk statement for each policy.
  - Right-click for "Show All Statements" in the main Policy Analysis tab.

#### b. *Statement Risk*
- **Purpose**: Fine-grained view—every statement scored, contextualized, and explained.
- **Features**:
  - Use dropdowns to adjust risk scoring factors.
  - Click a row for detailed risk/explanation.
  - Right-click for "Analyze Statement" in raw data tab.

---

### 3. **Superseded**
- **Purpose**: Identifies allow statements whose complete permission set is already granted by a single unconditional statement for the same principal at the same or an ancestor scope.
- **Features**:
  - Filter findings by compartment, including its descendant compartments.
  - Right-click a row and choose **Supersession Details** to see the candidate statement, coverage notes, applicable evidence statements and their scope relationship, and a permission-by-permission coverage comparison.
  - Conditional evidence is displayed for review, but is not used as proof of complete supersession.
  - In desktop mode, check findings and choose **Attempt/Fix** to add them to **Cleanup In Progress** with manual review instructions. Review the superseding permissions and any qualifications before removing a redundant statement in OCI; the button makes no OCI changes.
  - **Ignore Selected** hides findings for the active tenancy. **Show Previously Ignored** lets you restore them. Ignores survive reloads and restarts.
  - After your changes, **Reload All** verifies tracked supersession findings along with cleanup findings. Disabled checks are not treated as resolved.

---

### 4. **Policy Consolidation**
- **Purpose**: Flags policies or statements that could be combined/reorganized for clarity and management simplicity.
- **Features**: 
  - Groups similar statements by shared access, scope, and conditions when they differ only in their group or dynamic-group principals; the group can be reviewed as a consolidation opportunity.
  - Right-click any row and choose **Show Consolidation Opportunity** to inspect its rationale, commonality, participating policies and statements, and any proposed grouped statement.
  - When **Show Advanced Tabs** is enabled, select a supported group of statements with the checkboxes and choose **Create Consolidation Plan** to send that currently selected group to the **Consolidation Workbench**.
  - Advisory opportunities remain review-only; use their right-click details to evaluate them before making a manual change.

**Web parity update:** A dedicated **Consolidation Workbench** flow is available in web mode and can be used to review consolidation candidates and stage follow-up actions.

---

### 5. **Cleanup / Fix**
- **Purpose**: Lists invalid, risky, or redundant statements and unused IAM objects ready for cleanup (e.g., unused groups, overly broad statements).
- **Features**:
  - Select one or more issues using checkboxes.
  - **Attempt/Fix:**
    - Adds selected items to **Cleanup In Progress**; it does not execute changes in OCI.
    - Provides CLI/UI instructions, rollback, and tracks status/history.
  - **Ignore Selected**: Hides items from the list (persisted).
  - **Show Previously Ignored**: View/reset hidden items.
  - Right-click **Show Cleanup Details** to see the full statement or object name, the cleanup reason, and potential actions for that finding. The popup is read-only, scrollable, and supports copying text.
  - Guidance covers identity domain/name and spelling checks, unused-object ownership and planned use, limiting `any-user` conditions, and reviewing broad permissions with the administrator.
  - The right-click menu also provides direct navigation to the corresponding object/tab.

---

### 6. **Limits**
- **Purpose**: Displays compartment hierarchy and policy statement counts, with alerts for nearing/exceeding Oracle’s per-compartment statement limit (500).
- **Features**:
  - Filter compartments by status (all, nearing/over limit, only over limit).
  - See live statement counts and cleanliness recommendations.
  - Direct link to Oracle’s official limits documentation.

---

### 7. **Cleanup In Progress**
- **Purpose**: Tracks items added with **Attempt/Fix** from Cleanup/Fix or Superseded while you make changes in OCI. Items and history are saved locally per tenancy OCID and restored after restarting the application or returning to that tenancy.
- **Features**:
  - Table of all generated actions, with source/type/history.
  - Click to see CLI script, rollback instructions, UI workflow.
  - **Reload All**, beside **Clear**, refreshes IAM (domains, dynamic groups, groups, and users when enabled), compartments, and policies using the last successful live tenancy load settings. It then reruns intelligence and saves a full cache snapshot. It is disabled for cache/compliance loads and while another load is running.
  - After a successful reload, each tracked finding is marked **Open** if still present or **Resolved** if absent. Resolved rows stay visible with reload history. Ignoring a finding does not resolve it; disabled checks and failed reloads cannot establish resolution.
  - **Clear** removes the current tenancy’s saved rows and history, including resolved rows. It does not modify OCI resources or another tenancy’s progress.
  - Loading a different tenancy clears the previous tenancy’s visible analysis, selections, and progress; only the new tenancy’s own saved progress and consolidation history are restored.
  - A later successful, complete live load (desktop or web Settings) can verify saved progress against fresh intelligence. Cache/JSON/compliance loads restore the last recorded status without treating missing findings as resolved.
  - Cleanup progress lives in `~/.oci-policy-analysis/cache/cleanup/`, as `cleanup_<tenancy-OCID>.json`, matching the `prospects_<tenancy-OCID>.json` and `consolidation_<tenancy-OCID>.json` naming convention in their respective folders. Older hashed cleanup files remain readable and migrate on the next save. It is independent of inventory snapshots and consolidation plans; credentials are not stored in progress files.
  - To verify a dynamic-group fix: add the finding with **Attempt/Fix**, correct its policy reference in OCI, then click **Reload All** and inspect its status.

**Desktop workflow:** The live reload and resolution tracking described here apply to the desktop Cleanup In Progress tab.

---

## Usage Tips & Workflow Suggestions

- **After loading data**, always review the Summary Table for high-priority risks and limits issues first.
- **Use filters and sorts** in every tab to focus on what's most important for your tenancy or project.
- **Take Action on actionable issues** directly from Cleanup/Fix—a fast route to trackable and auditable remediation steps.
- **Interpret why an issue is flagged** by expanding details in each table—most analytics include clear rationale and recommended next steps.
- **Reload regularly:** If you make changes in OCI Console or via CLI, click **Reload All** in **Cleanup In Progress** to verify tracked findings against fresh live data.

---

**Other Reading:**  
- [Overview](overview.md)
- [Architecture](architecture.md)
- [Simulation](simulation.md)
- [MCP Server and Tools](mcp.md)
- [Usage and UI Guide](usage.md)
- [Managing IAM Policies in Compartment Hierarchy (A-Team Blog)](https://www.ateam-oracle.com/managing-iam-policies-in-compartment-hierarchy)
