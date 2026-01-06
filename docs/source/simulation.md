# Simulation

OCI Policy Analysis provides a robust simulation engine allowing users to test OCI IAM policy statements, conditions (where-clauses), principal identities, and permissions against real-world scenarios—without making changes in OCI or risking live resources. Simulation lets you see whether a specific OCI API action would be ALLOWED or DENIED, what policy logic is triggered, and what variable values affect the outcome. This is a core tool for security review, troubleshooting, and policy development.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Components of a Simulation](#components-of-a-simulation)
3. [Loading and Editing Where-Clause Variables](#loading-and-editing-where-clause-variables)
4. [Running the Simulation](#running-the-simulation)
5. [Interpreting Results](#interpreting-results)
6. [Simulation History](#simulation-history)
7. [Best Practices & Advanced Usage](#best-practices--advanced-usage)
8. [Related Features & See Also](#related-features--see-also)

---

## Introduction

The simulation feature enables users to answer questions such as:
- "If user Alice tries to run the `ListDomains` API in Compartment Finance, would she be allowed?"
- "What happens if a specific `where` clause or variable is set?"
- "Why does a set of policy statements not grant expected permissions in a scenario?"

Simulations are performed via the Simulation tab in the GUI, or in a simplere form via Condition Tester tab (for where-clause parsing)

---

## Components of a Simulation

A simulation consists of the following components:

- **Effective Compartment/Context:** The compartment where the action occurs, following OCI's compartment hierarchy rules.  Recall that permissions cascade to lower compartments, so this is taken into account.
- **Principal Type:** Who is requesting access? This could be a User, Group, Dynamic Group, or Service.  Resource Principals can be simulated via `any-user` principal.
- **Principal:** A specific principal (user,group, dynamic group, service) of the selected type. All applicable policy statements for that principal are required to load for the simulation to be complete.
- **Policy Statements Under Test:** All relevant policy statements, including any that may apply via inheritance or overlapping compartments. These can be unselected, for example, to test removal of a policy statement and the effect on an operation.
- **Where-Clause and Conditions:** Any conditions or expressions (e.g., `where request.principal.type = ...`) in the policy set that will affect the simulated permissions added to the final permission set.
- **Variable Values:** Values required by where-clauses (OCIDs, strings, lists, booleans), which are set or simulated as part of the scenario.
- **API Operation:** The specific operation to be tested.  All OCI API Operations require a set of permissions, and will fail if any required permission is missing.  
- **History:** If multiple simulations are run, the history of what has been performed, with the ability to export to JSON.

---

## Loading and Editing Where-Clause Variables

Some policy statements include *where-clauses* or conditions, which require additional context or variables for evaluation.

**How Variable Loading Works:**
- The simulation engine parses the selected policy statement(s) and identifies required variables.
- The UI (Simulation or Condition Tester tab) presents these variables as input fields, showing:
  - Variable name (e.g., `request.networkSource.name`)
  - Examples, if any are needed, such as for timestamps
- For each simulation run, users set values either manually or use previous/test values.

**Example:**
Suppose a statement contains:
```plain
allow group SecurityAdmins to use database-family in compartment Data where all {request.principal.name = 'alice', request.networkSource.name = 'trusted-src'}
```
Simulation UI will prompt for:
- `request.principal.name` (string)
- `request.networkSource.name` (string)

Values set here directly affect simulation outcome.  Specifically, the set of PERMISSIONS that correspond to `use database-family` are now added to the final "permission set" for the simulation.  

---

## Deny Statements

The simulation takes into account `deny` statements, by saving them until last.  All of the allowed permissions are first calculated, and then any permissions that are denied are subtracted.   The trace log shows this activity, so it will be possible to see that a principal might have had a certain permission, had it not been denied as well.

Denial is the opposite of allow, and can remove a component of a family, even at a different level in the hierarchy.  For example, consider these statement:

```
allow group A to manage object-family in compartment Top
deny group A to {OBJECT_DELETE, BUCKET_DELETE} in compartment Top:Second
```

In this case, `manage object-fmaily` is very broad and has many individual permissions.  Because it is granted at a top-level compartment, it cascades to all sub-compartments.  Denying deletion to a sub-compartment is a good way to pinpoint an action.  The simulation can easily show this. 

More on [Deny Statements](https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/denypolicies.htm).

## Running the Simulation

**Steps:**

1. **Pick Compartment/Context**  
   Choose the compartment where the simulated action will occur.

2. **Select the Principal**   
   Choose the type - then the specific user, group, dynamic group, or principal you wish to simulate as.

3. **Load and Select Statements**  
   Select the policy statements from the search to include.  The default list is all policy statements applicable to the principal for the effective compartment.  This includes statements at a higher compartment level that grant permissions to the principal.  

4. **Configure Where-Clause Variables**  
   The UI will prompt for all potential variables parsed from any policy where-clause that applies.  Any where clause for a statement will cause the simulation to add or not add the permissions in that statement based on whether the where clause evaluates as True or False.

5. **Choose API Operation**
   API Operations are documented as part of the OCI Policy Reference.  Not all API Operations or Permissions are available in the simulation, but many of the major ones are.

6. **Run Simulation**  
   Click 'Run Simulation' or use the trace — the engine will:
   - Evaluate applicable policy statements for the principal/resource/context.
   - Parse and substitute variables in where-clauses.
   - Resolve deny/allow ordering, overlapping/inherited policies, etc.
   - Test the final permission set for the entire context again what the API requires
   - Keep a history of simulations run.

6. **View Results**  
   Results (ALLOW/DENY and decision path/traces) will be shown, including which policy/condition was matched, which variables were set, and any relevant notes.

**Multiple Scenarios:**  
You can batch test by changing variable values or choosing different principals/resources without leaving the simulation UI.

---

## Interpreting Results

A successful simulation gives you:

- **Decision:** ALLOW or DENY.
- **Policy Trace:** Which statement(s) granted or denied the action.
- **Variable Substitution:** Actual variable values used in the where-clause for the decision.
- **Match/No-Match Reasons:** Why a statement matched (or not); e.g., mismatched variables, compartment scoping, lack of group membership.
- **Raw Evaluation Trace:** (Advanced/troubleshooting) Step-by-step evaluation—helpful when debugging unexpected outcomes.

**Example Output:**
```
Simulation Result: ALLOW
Matched Policy: allow group SecurityAdmins to use database-family ...
Effective Path: ROOT/Finance/Data
Where Clause: request.principal.name = 'alice', request.networkSource.name = 'trusted-src'
Trace: All conditions matched, group membership confirmed.
```

---

## Simulation History

Simulation runs are automatically stored for later review.

- Each run logs:
  - Principal/identity under test
  - Resource/action simulated
  - Compartment/context
  - Where-clause variables/values
  - Date/time
  - Outcome (allow/deny, matched statement)
- History is accessible from the Simulation tab (History panel/button) or exported as JSON/CSV.
- Useful for audits, regression testing, and sharing simulation sessions with other users.

---

## Best Practices & Advanced Usage

- Use simulation before deploying new or changed IAM policies to validate intended effects.
- Test edge cases: users in multiple groups, nested dynamic groups, overlapping compartments.
- Vary variable inputs ("what-if?" analysis) to see possible decision outcomes.
- Use history for compliance evidence or troubleshooting intermittent issues.

---

## Related Features & See Also

- [Condition Tester Tab](./usage.md#condition-tester)  
  - Quickly validate and experiment with where-clauses in isolation.

- [Policy Overlap Tab](./usage.md#policy-overlap-tab)  
  - Analyze which statements could interact or supersede each other.

- [MCP Server](./mcp.md)  
  - Run simulations programmatically, enabling integration with AI tools or CLI automation.

- [Permissions Report](./usage.md#permissions-report-tab)  
  - See all permissions granted/denied as a result of current policies.

---

**Need more details or have an advanced simulation scenario?**  
Refer to the project's GitHub issues or submit a question for more simulation examples!
