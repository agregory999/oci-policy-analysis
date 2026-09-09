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
- **Tips**: Each row summarizes an actionable item. Clicking "Reload All" at the top will refresh these based on current data.

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
  - **Take Action:**  
    - Sends selected items to the Recommendation Workbench.
    - Provides CLI/UI instructions, rollback, and tracks status/history.
  - **Ignore Selected**: Hides items from the list (persisted).
  - **Show Previously Ignored**: View/reset hidden items.
  - Right-click for direct navigation to the corresponding detailed object/tab.

---

### 6. **Limits**
- **Purpose**: Displays compartment hierarchy and policy statement counts, with alerts for nearing/exceeding Oracle’s per-compartment statement limit (500).
- **Features**:
  - Filter compartments by status (all, nearing/over limit, only over limit).
  - See live statement counts and cleanliness recommendations.
  - Direct link to Oracle’s official limits documentation.

---

### 7. **Recommendation Workbench**
- **Purpose**: Collects "one-off" actions you’ve taken from Cleanup/Fix (or in future: Overlap/Consolidation), allowing you to track, script, and review all remediations in one session.
- **Features**:
  - Table of all generated actions, with source/type/history.
  - Click to see CLI script, rollback instructions, UI workflow.
  - "Clear" removes all workbench items for a fresh state.
  - When you "Reload All" or update policy data, resolved issues disappear; history per action is retained.

**Web parity update:** The web UI includes equivalent workbench behavior (including consolidation-oriented flows), with the same core objective: track actionable items and retain operator-friendly remediation context.

---

## Usage Tips & Workflow Suggestions

- **After loading data**, always review the Summary Table for high-priority risks and limits issues first.
- **Use filters and sorts** in every tab to focus on what's most important for your tenancy or project.
- **Take Action on actionable issues** directly from Cleanup/Fix—a fast route to trackable and auditable remediation steps.
- **Interpret why an issue is flagged** by expanding details in each table—most analytics include clear rationale and recommended next steps.
- **Reload regularly:** If you make changes in OCI Console or via CLI, clicking "Reload All" refreshes analytics and cleans up completed workbench items.

---

**Other Reading:**  
- [Overview](overview.md)
- [Architecture](architecture.md)
- [Simulation](simulation.md)
- [MCP Server and Tools](mcp.md)
- [Usage and UI Guide](usage.md)
- [Managing IAM Policies in Compartment Hierarchy (A-Team Blog)](https://www.ateam-oracle.com/managing-iam-policies-in-compartment-hierarchy)
