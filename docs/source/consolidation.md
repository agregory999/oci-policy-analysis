# Consolidation planning

The Consolidation Workbench helps you plan policy simplification without directly
changing OCI. A plan records the policy changes that would be needed, the statements
that cannot safely move, and the information needed to reverse each step.

This is an advanced feature. Review generated statements, target compartments, and
rollback output before applying any CLI command in a tenancy.

## Plan lifecycle

```{mermaid}
flowchart LR
    A[Select consolidation candidates] --> B[Choose strategy]
    B --> C[Validate candidate data and protections]
    C --> D[Strategy selects target policy placement]
    D --> E[Rewrite statement location when necessary]
    E --> F[Build target ADD or MODIFY steps]
    F --> G[Build source MODIFY or DELETE steps]
    G --> H[Attach rollback snapshots]
    H --> I[Validate OCI policy statement limit]
    I --> J[Review execution and rollback output]
```

Plans are declarative. Generating one does not execute it. The workbench and CLI
render steps for an operator to review and apply.

## Built-in strategies

| Strategy | Target selection rule | Best fit |
|---|---|---|
| Group Similar Statements | Creates a new policy in the common source-policy compartment with one canonical, de-duplicated list of named groups or dynamic groups. | Statements that are identical in action, scope, permissions, location, conditions, and comments, and differ only in named principals. |
| Statement Density (Pack Policies) | Reuses the eligible policy containing the most selected statements. | Reducing policy count while retaining a legal shared scope. |
| Move to Root | Creates one root policy. | Statements that need centralized management and remain safe at tenancy scope. |
| Move Down Next Level | Moves a source policy to the immediate shared child scope. | A cautious, single-level policy descent. |
| Move Closer to Target | Uses the lowest common effective scope, then chooses the deepest safe policy compartment above it. | Moving a policy closer to related resources while retaining shared coverage. |
| Move Into Target | Places each statement in its direct effective-path compartment. | Maximum locality, potentially creating or changing more policies. |

All strategies exclude protected statements and report candidates they cannot safely
place. OCI policies are limited to 50 statements; a plan that would exceed that limit
is rejected before it can be rendered for execution.

## Placement and materialization

Strategies are intentionally split into two concerns:

```{mermaid}
classDiagram
    class BaseConsolidationStrategy {
      +planning_context()
      +effective_candidates()
      +empty_plan()
      +finalize_plan()
      +rollback_for_step()
    }
    class PlanningContext {
      statements_by_id
      policies_by_ocid
      policies_by_location_and_name
      compartments
      root_ocid
    }
    class TargetPolicySpec {
      compartment_ocid
      hierarchy_path
      policy_name
    }
    class StatementPlacement {
      internal_id
      source_policy_ocid
      target
    }
    BaseConsolidationStrategy --> PlanningContext
    StatementPlacement --> TargetPolicySpec
```

A strategy owns the placement decision: where an eligible statement should live and
which policy should receive it. Shared planner helpers own repository indexes,
candidate filtering, common plan metadata, and the immutable before/after snapshots
needed by execution and rollback.

## Rollback

Every non-empty generated plan step has structured rollback metadata derived from its
pre-plan state:

- An **ADD** step records that the policy created during execution must be deleted.
- A **MODIFY** step records the original statements and tags to restore.
- A **DELETE** step records the policy name, description, compartment, statements,
  and tags needed to recreate it.

This metadata supplements the existing rendered rollback instructions. It does not
automatically execute OCI changes. Keeping it in the plan model makes a future
controlled rollback executor possible without re-reading a tenancy that may have
changed since the plan was created.

## Adding a strategy

1. Create a small strategy class in `application/core/engine/strategies/`.
2. Inherit from `BaseConsolidationStrategy` and declare `strategy_id`,
   `display_name`, and `required_capabilities`.
3. Build a `PlanningContext` once at the start of `build_plan`.
4. Define the placement rule in terms of `TargetPolicySpec` and
   `StatementPlacement`. Keep policy selection logic in the strategy.
5. Reuse common helpers for candidate filtering, empty plans, target lookup, and
   final plan metadata. Do not recreate OCI rollback snapshots by hand.
6. Register the strategy in `ConsolidationEngine` and add it to the package export.
7. Add behavior tests plus shared contract tests for protected candidates, target
   creation or reuse, source cleanup, location rewriting, OCI limits, and rollback.

Keep new strategies explicit. A strategy class should read like a policy-placement
rule, not a generic configuration entry whose behavior is difficult to audit.

### Group Similar Statements

Use this strategy when several statements grant the same access at the same scope
but name different groups. It accepts named `group` and `dynamic-group` subjects
only. It does not try to merge ID-based subjects or other principal types.

The statements must match on allow/deny action, effective path, policy
compartment, location, verb/resource or permission set, where clause, and
comments. The named principals are collected from every matching statement,
de-duplicated, and rendered as `domain/group`. A group written without a domain
is rendered as `Default/group` in the new statement.

The strategy creates a new policy in the source policy compartment. It does not
choose one of the existing policies as the survivor. That keeps the location text
unchanged and leaves a clear audit trail: create the grouped policy, then modify
or remove each source policy. Rollback removes the new policy and restores the
source policies from the plan snapshot.

## Operator review checklist

Before applying a plan:

1. Confirm the selected candidates and any skipped-statement reasons.
2. Read each rewritten statement and its target compartment.
3. Confirm source policies keep all non-selected statements.
4. Confirm no target policy exceeds the OCI 50-statement limit.
5. Save and review the rollback section before applying execution commands.
6. Reload policy data after execution and use the plan status to check for drift.

## Recommendation opportunities

The Policy Consolidation view lists opportunities, not individual statements.
The table stays short enough to scan: type, number of policies, number of
statements, scope, a one-line reason, and the next action.

Open the evidence before planning a change. In the desktop application,
right-click a row and select **Show Consolidation Opportunity**. In the web
application, click the row to open the detail panel on the right. Both views
show the policies and statements that make up the opportunity, the shared
attributes, and the proposed grouped statement when there is one.

An opportunity may be actionable or advisory:

| Opportunity | How rows are formed | Workbench handoff |
|---|---|---|
| Policy Grouping | All statements that can become one multi-principal `group` or `dynamic-group` statement. They may come from more than one policy. | Sends the complete statement set and selects **Group Similar Statements**. |
| Policy Placement | Statements from one source policy with the same effective target path. Statements from different policies or paths remain separate opportunities. | Sends the statement set; choose the placement strategy in the workbench. |
| Duplicate Scope / Single-statement Policy | A comparison or cleanup hint rather than a prescribed edit. | Review only. No workbench handoff is offered. |

Only actionable rows have a checkbox in the desktop view. On the web, the
right-click menu offers **Send to Consolidation Workbench** only for actionable
rows. The handoff replaces the current candidate selection in the workbench; it
does not delete saved plans or their rollback information.

When the web handoff opens the Consolidation Workbench, the page validates the
statement IDs against the current candidate list. Protected, invalid, and system
policy statements remain excluded. Review the selected candidates and generate a
new proposal in the workbench as usual.
