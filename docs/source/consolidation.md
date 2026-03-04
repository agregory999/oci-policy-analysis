# Policy Consolidation

Consolidation is the process of reducing the complexity and redundancy within a set of IAM policy statements, making policies easier to understand, manage, and audit. For OCI administrators, well-consolidated policies improve both the security posture and maintainability of a cloud tenancy.

This document introduces the concept of consolidation, describes what the consolidation engine and strategies in OCI Policy Analysis can do, and summarizes best practices for effective, safe consolidation.

---

## What is Policy Consolidation?

In OCI IAM, policies often evolve over time—statements are added to address new requirements and sometimes overlap or contradict prior permissions. Left unchecked, this leads to:
- Redundant or overlapping permissions
- Confusing intent or ambiguous access boundaries
- Ineffective risk controls and hard-to-audit policies

**Policy consolidation** is the act of combining, streamlining, or restructuring policy statements so that:
- Each permission is granted in only one place (or the minimum necessary places)
- Overlaps and contradictions are removed or clearly justified
- The total number of policy statements is manageable
- Policy meaning and risk exposure are clear to those responsible

Consolidation is not just a cleanup—it is a security best practice. Leaner, clearer policies reduce errors and support sustainable cloud operations.

---

## The Consolidation Engine & Strategy Capabilities

OCI Policy Analysis provides a **consolidation engine** that can:

- **Analyze** policy statements and detect opportunities for consolidation, including statements with overlapping subjects, verbs, resources, or locations.
- **Propose** grouping similar statements, moving statements closer to effective compartments, or restructuring for better clarity.
- **Suggest** removals or rewrites where a single comprehensive statement can replace several granular ones.
- **Detect** risky patterns, such as broad permissions granted via multiple statements when a single, tighter control is safer.

### Main Strategies Include:
- **Move closer to target**: Identifies statements that can be moved down (or up) the compartment hierarchy without changing effective permissions, reducing unnecessary exposure.
- **Move into target**: Moves each selected statement into a policy at the *exact* compartment specified by its effective path. Unlike LCA-based approaches, this ensures every statement lands in the precise compartment matching its scope, and creates/modifies policies as needed for each location.
- **Statement density**: "Packs" statements into container policies.  For example, if there are many policies with 1-2 statements, consolidate into a couple policies with more statements in each.
- **Move to root**: Detects cases where moving statements to root (for visibility or broader coverage) could simplify policy management, or the reverse if scoping needs to be narrowed.

The engine does *not* automatically rewrite policies but provides recommendations, analyses, and what-if scenarios before any changes are made.

---

## Best Practices for Policy Consolidation

To maximize both safety and clarity, follow these best practices:

### 1. Select Manageable Chunks
- Do not attempt to consolidate all policies at once, especially in large tenancies.
- Select a single compartment, principal, or resource as your focus.

### 2. Focus on a Single Risk or Permission at a Time
- Pick one access area where overlap is high, or risk/complexity is greatest.
- Reconcile statements relating to that target, then move to the next.

### 3. Use Analysis & Simulation Tools
- Employ the consolidation engine and overlap analysis to preview what can be merged, moved, or deleted.
- Use simulation features to verify before/after outcomes for various principals and API operations.

### 4. Validate with Testing
- Always test policy changes in a non-production environment or with simulation to confirm no loss of legitimate access or unwanted escalation has occurred.
- Validate both direct and inherited permissions.

### 5. Understand and Prepare Rollback Plans
- Before consolidating, establish a rollback path: keep old statements available and document reasoning.
- If new permissions fail or risk increases, promptly revert to the prior configuration.

### 6. Audit and Document Changes
- Record which statements are merged or altered, and why.
- Use documentation and internal audit trails to justify the change and support future reviews.

---

## When *Not* to Consolidate

- Where similar-looking statements differ for a justified business reason (e.g., scoping, temporary exceptions).
- If consolidation would obscure necessary audit trails or regulatory requirements.
- When downstream systems or users are sensitive to access pattern changes.

---

## Summary

Policy consolidation, when performed systematically and thoughtfully, helps reduce risk, improve auditability, and make OCI environments easier to manage. Leverage automation and analysis features in OCI Policy Analysis to guide your process, but always combine them with deliberate, well-documented operational procedures.

For more information on using simulation and analysis tools to support consolidation, see the [Simulation](./simulation.md), [Recommendations](./recommendations.md), and [Architecture](./architecture.md) documentation.