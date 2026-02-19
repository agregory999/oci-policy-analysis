# Context: Policy Intelligence Engine and Recommendations UI Integration

This file describes how the policy analytics/engine layer and the unified recommendations UI tab interact in the OCI Policy Analysis project. It serves as the source of truth for updating/expanding related features.

---

## 1. Overview

- **PolicyIntelligenceEngine (`logic/policy_intelligence.py`)**:  
  Performs all post-load analysis, risk scoring, overlap detection, cleanup, and high-level recommendation synthesis on loaded policy data.
- **PolicyRecommendationsTab (`ui/policy_recommendations_tab.py`)**:  
  Provides a unified UI notebook/tab for exploring analytics results—risk scores, overlaps, fix actions, and more—produced by the engine.

Together, they enable deep, actionable insight into Oracle Cloud policies, with a strong separation between analytics logic and its interactive presentation.

---

## 2. Data Flow and Integration

- After policy data is loaded, the **PolicyIntelligenceEngine** is initialized with a reference to the PolicyAnalysisRepository.
- The engine analyzes all policy statements and identity data, populating a single "overlay" structure (`self.overlay`, using the canonical PolicyIntelligence models).
- Overlay keys/results include:
  - `risk_scores`: Score, notes, and recommendations per statement
  - `overlaps`: Detected policy statement supersessions/conflicts
  - `consolidations`: Policies/statements that could be merged or simplified
  - `cleanup_items`: Actionable fix suggestions (invalid/inactive/overbroad)
  - `recommendations`: High-level actions for users (summarized from above)
- The **PolicyRecommendationsTab** fetches overlay data directly from the engine to populate:
  - **Summary Table** (top): Main recommendations (with priority, action)
  - **Sub-tabs**:
    - Risk: Scored statements, detailed notes, and suggested actions
    - Overlap: Conflicts, superseding statements, and resources/compartments involved
    - Consolidation: Opportunities to combine policies/statements
    - Cleanup: Actionable fixes by type (invalid, unused, overly broad, etc.)
    - [Future]: For extending analytics/visualizations

---

## 3. Extensibility and Feature Update Workflow

**To add/extend analytics or recommendations:**
- Document the new analytic or recommendation type here, under the appropriate overlay key or subtab heading.
- Implement computation and overlay population in `policy_intelligence.py` (`self.overlay[...]`).
- Update the corresponding subtab or summary table in `policy_recommendations_tab.py` to render the new analytic output, add controls, or expose new actions.
- (Optional) Update table layouts/column configs for new fields as needed.

**Examples of extensible areas:**
- Adding new category to `cleanup_items` (e.g., "statements missing comments")
- Adding a risk or exposure metric to `risk_scores`
- Enabling direct remediation actions from the UI (for fixable issues)
- Enhancing the overlap engine to detect more subtle supersession patterns

---

## 4. Coupling and Boundaries

- The analytics layer NEVER invokes UI directly; it only populates overlay data.
- The UI tab makes no analytic decisions—it simply renders the latest overlay analytic state and triggers recalculation on user reload/action.
- All shared structures (overlay keys, inner dict formats) are defined in typed models for both clarity and type safety.

---

## 5. References

- Policy Intelligence Engine: [`src/oci_policy_analysis/logic/policy_intelligence.py`](../../../src/oci_policy_analysis/logic/policy_intelligence.py)
- Recommendations Tab UI: [`src/oci_policy_analysis/ui/policy_recommendations_tab.py`](../../../src/oci_policy_analysis/ui/policy_recommendations_tab.py)

---

**Summary:**  
All policy recommendations, advanced analysis, and clean-up opportunities are computed in the engine and delivered to the UI through a typed overlay structure. Additions or enhancements here should always start by updating this file, ensuring new features are well-documented before implementation.