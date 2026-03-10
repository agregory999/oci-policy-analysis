# Recommendations Tab: Guided Policy Analytics & Remediation

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

### 3. **Overlap Analysis**
- **Purpose**: Identify policies/statements that overlap, conflict, or supersede each other (potential misconfiguration).
- **Features**:
  - Filter by compartment or resource using dropdowns.
  - See details on why and where overlap occurs by selecting a row.
  - Use right-click actions to drill deeper.

---

### 4. **Policy Consolidation**
- **Purpose**: Flags policies or statements that could be combined/reorganized for clarity and management simplicity.
- **Features**: 
  - Checkbox selection to review candidates.
  - (Actions require manual follow-up in current version.)

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
- **Purpose**: Displays compartment hierarchy and policy statement counts, with alerts for nearing/exceeding Oracle’s hard per-compartment statement limit (500).
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

---

## Usage Tips & Workflow Suggestions

- **After loading data**, always review the Summary Table for high-priority risks and limits issues first.
- **Use filters and sorts** in every tab to focus on what's most important for your tenancy or project.
- **Take Action on actionable issues** directly from Cleanup/Fix—a fast route to trackable and auditable remediation steps.
- **Interpret why an issue is flagged** by expanding details in each table—most analytics include clear rationale and recommended next steps.
- **Reload regularly:** If you make changes in OCI Console or via CLI, clicking "Reload All" refreshes analytics and cleans up completed workbench items.
- **Curious about technical details?** See below.

---

## Further Reading: AI Context & Detailed Architecture

Curious about the deep technical contract behind this tab?  
All analytic findings, dashboard subtabs, workbench logic, and extensibility are governed by a formal, pluggable overlay model and a set of modular strategy "plug-ins." If you're an advanced user, developer, or just want a full description of how analytics are constructed (with diagrams, wiring, and extensibility guides), see:

**Policy Intelligence Engine & Recommendations UI — AI Context**

[context/project/CONTEXT_policy_intelligence_and_recommendations.md](context/project/CONTEXT_policy_intelligence_and_recommendations.md)

This "AI Context" is the source of truth for the analytic and UI contract. It covers:
- Overlay data model and all canonical output structures
- Pluggable strategies and how to extend/reason about them
- Control/data flow diagrams for engine, plug-ins, overlay, and UI
- Extensibility/workbench details and all implementation references

---

**Other Reading:**  
- [Overview](overview.md)
- [Architecture](architecture.md)
- [Simulation](simulation.md)
- [MCP Server and Tools](mcp.md)
- [Usage and UI Guide](usage.md)
- [Managing IAM Policies in Compartment Hierarchy (A-Team Blog)](https://www.ateam-oracle.com/managing-iam-policies-in-compartment-hierarchy)
