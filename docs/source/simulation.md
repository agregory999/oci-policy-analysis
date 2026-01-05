# Simulation

OCI Policy Analysis provides a robust simulation engine allowing users to test OCI IAM policy statements, conditions (where-clauses), principal identities, and permissions against real-world scenarios—without making changes in OCI or risking live resources. Simulation lets you see whether a specific action would be ALLOWED or DENIED, what policy logic is triggered, and what variable values affect the outcome. This is a core tool for security review, troubleshooting, and policy development.

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
- "If user Alice tries to **manage** a Database in Compartment Finance, would she be allowed?"
- "What happens if a specific `where` clause or variable is set?"
- "Why does a policy statement not grant expected permissions in a scenario?"

Simulations are performed via the Simulation tab in the GUI, via Condition Tester tab (for where-clause parsing), or programmatically with the MCP server.

---

## Components of a Simulation

A simulation consists of the following components:

- **Principal Identity:** Who is requesting access? This could be a User, Group, Dynamic Group, or Resource Principal.
- **Target OCI API/Resource:** The resource and action the principal is attempting (e.g., `manage instance-family` in `compartment A`). Can simulate specific API calls and resources.
- **Policy Statements Under Test:** All relevant policy statements, including any that may apply via inheritance or overlapping compartments.
- **Effective Compartment/Context:** The compartment where the action occurs, following OCI's compartment hierarchy rules.
- **Action/Verb:** The OCI IAM verb (manage, use, read, inspect) and optionally the specific operation or permission.
- **Where-Clause and Conditions:** Any conditions or expressions (e.g., `where request.principal.type = ...`) in the policy that affect the simulated decision.
- **Variable Values:** Values required by where-clauses (OCIDs, strings, lists, booleans), which are set or simulated as part of the scenario.

---

## Loading and Editing Where-Clause Variables

Some policy statements include *where-clauses* or conditions, which require additional context or variables for evaluation.

**How Variable Loading Works:**
- The simulation engine parses the selected policy statement(s) and identifies required variables.
- The UI (Simulation or Condition Tester tab) presents these variables as input fields, showing:
  - Variable name (e.g., `request.networkSource.name`)
  - Expected type (string, OCID, boolean, list, etc)
  - Default or previously used value (if any)
- For each simulation run, users set values either manually or use previous/test values.

**Example:**
Suppose a statement contains:
```plain
allow group SecurityAdmins to use database-family in compartment Data where request.principal.name = 'alice' and request.networkSource.name = 'trusted-src'
```
Simulation UI will prompt for:
- `request.principal.name` (string)
- `request.networkSource.name` (string)

Values set here directly affect simulation outcome.

---

## Running the Simulation

**Steps:**

1. **Select the Principal**   
   Choose the user, group, dynamic group, or principal you wish to simulate as.

2. **Set Resource/Action**  
   Select the OCI resource type and verb/action (e.g., manage, use, read—see dropdowns in Simulation tab).

3. **Pick Compartment/Context**  
   Choose the compartment where the simulated action will occur.

4. **Configure Where-Clause Variables**  
   The UI will prompt for all "required" variables parsed from any policy where-clause that applies.

5. **Run Simulation**  
   Click 'Simulate' or similar—the engine will:
   - Evaluate applicable policy statements for the principal/resource/context.
   - Parse and substitute variables in where-clauses.
   - Resolve deny/allow ordering, overlapping/inherited policies, etc.

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
- Combine with batch simulation tools for full-scale policy regression tests (future feature).

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
