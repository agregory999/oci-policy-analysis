# Policy consolidation

Policy consolidation is the process of reducing or reorganizing IAM policy
statements without changing the access they grant. It is useful when policies have
grown through repeated changes, several statements express the same intent, or a
policy needs to live closer to the resources it governs.

The Consolidation Workbench does not change OCI for you. It prepares a plan,
including execution and rollback instructions, for an operator to review and apply.
Treat every proposal as a change plan, not as an automatic cleanup.

## Enable the workbench

In the desktop application, open **Settings** and select **Show Advanced Tabs**.
This exposes **Consolidation Workbench (Preview)**. The workbench is available
after a dataset has been loaded.

The web application has a **Consolidation Workbench** page. It follows the same
four-stage flow: protection, candidates, proposal, and history.

## Start with a recommendation or start directly

There are two sensible entry points:

- In **Policy Recommendations**, open the **Policy Consolidation** subtab. Filter
  by consolidation type or search for a policy, then inspect the opportunity
  before acting. Actionable opportunities can be sent to the workbench with their
  statements already selected. Advisory rows, such as a single-statement policy,
  are prompts for review rather than a prescribed change.
- Open the workbench directly when you already know the policies or statements you
  want to reconsider. This is useful for a focused cleanup after a change window
  or before a policy limit is reached.

Sending an opportunity to the workbench replaces the current candidate selection.
It does not remove saved plans or protected statements.

## The consolidation flow

### 1. Protect statements that must not move

Start in **Policy/Statement Protection**. Search by policy name or statement text,
check the policies or statements that must remain untouched, and select **Save
Protected**. Use **Save and Select Consolidation Statements** when you are ready
to continue to candidate selection.

Protected statements are excluded from every proposal. The protected set is saved
with the tenancy's cached consolidation data, so it remains available when that
dataset is reopened. It is a planning safeguard only; it does not add a tag or
otherwise alter the OCI policy.

### 2. Choose candidates

In **Candidate Selection & Strategy**, use **Search/Filter** to narrow the list,
then check the statements you want the plan to consider. The table keeps the
selection while you change the search text, and the selected-candidates area shows
the full set that will be used.

The workbench deliberately omits protected statements, invalid statements, and
statements in locked system policies. The counts beside the filter make those
exclusions visible. A statement missing from the candidate list is not silently
included in a proposal.

### 3. Pick a strategy that matches the problem

Choose a value from the **Strategy** list before selecting **Create Consolidation
Proposal**. A strategy answers two practical questions: which statements belong
together, and where should the resulting policy live. There is no universally
correct choice.

| Strategy | Use it when | What it plans |
|---|---|---|
| **Group Similar Statements** | Statements have the same access, scope, and conditions but name different groups or dynamic groups. | A new grouped statement with the named principals combined in a comma-separated subject. |
| **Statement Density (Pack Policies)** | You want fewer policies with more statements in each. | Reuse of an eligible policy that already contains many of the selected statements, and deletion of single-statement policies. |
| **Move to Root** | Ease of use for smaller tenancies | Moves selected statements to root compartment and adjusts location so that compartment scope is unchanged. |
| **Move Down Next Level** | You want to move statements away from root to relieve limit pressure. | Moves selected statements down to next compartment in the location. |
| **Move Closer to Target** | Statements should be managed nearer to the compartment they affect but still cover a shared area. | Chooses the lowest compartment that is common to selected statements, and adjusts the location of each statement. |
| **Move Into Target** | Each statement belongs with its direct effective compartment. | Moves all candidate statements into new policies in the effective compartment. |

The plan can skip a selected statement when it does not meet a strategy's safety
rules. Review the skipped-statement reason rather than trying to force it through.

### 4. Generate and review the proposal

Select **Create Consolidation Proposal**. The workbench creates an ordered plan
and opens **Consolidation Proposal**.

Review these parts before making any OCI change:

- **Plan Elements** shows the proposed add, modify, and delete steps and their
  target policies.
- **Skipped Statements** explains statements that were selected but could not be
  included safely.
- **Plan Notes** lets you save the decision context with the plan.
- **Proposed Script / Batch Output** can show OCI CLI commands or OCI Console
  steps. Use **Show** to switch between execution instructions, rollback
  instructions, or both.

The planner checks the target policy's statement capacity before it renders a
proposal. It also keeps the original state needed for the rollback instructions.
Still review the resulting statements, target compartment, source-policy cleanup,
and rollback steps yourself. Apply the approved commands or Console steps outside
the application.

## Plans, history, and progress checks

Every generated plan is stored in the consolidation history for the loaded
tenancy. Use **Select Consolidation Plan** or the **Plan History** tab to reopen a
proposal. **View in Proposal** restores the selected plan and its output.

For a cache or CIS compliance dataset, the application has no live tenancy to
query. You can still create, review, save, and reopen plans, but progress checking
uses the stored state and does not claim to verify OCI changes.

Use **Reset Consolidations for Tenancy** only when you want to discard the saved
protected set and plan history for that tenancy. It removes local consolidation
state; it never removes or edits OCI policies.

### How Progress Check works

After applying a plan, **Reload and Check Progress** reloads policy data from OCI
and compares the live tenancy with the saved plan. It records completed steps and
flags conflicting consolidation markers where applicable. This button is enabled
only for a live tenancy load.

The progress check on a generated plan looks at all current policies it knows about.  When 
a plan is generated, tags are inserted into the recommended plan steps for each add/update.
After reloading data from the live tenancy, newly changed or added policies will carry the tag
if the statement recommended to run was run as-is. The planner will see these as having the tag
and mark that step as executed in the plan.   Failure to run the exact statement shown may 
create unexpected results.

## Before you apply a plan

1. Confirm the candidate list and every skipped-statement reason.
2. Read the proposed statement text and its target compartment.
3. Confirm source policies retain statements that are not part of the plan.
4. Review the execution and rollback output together.
5. Apply the steps through the OCI CLI or Console under your normal change
   controls.
6. If working against a live tenancy, return to the workbench and select
   **Reload and Check Progress**.

## Tips

Here are a few tips to successful use of the Consolidation Workbench:
1. Test the consolidation workbench with a small number of known statements.  Ideally you can 
identify a scenario via looking at a couple policy statements on the other tabs. Plan a 
consolidation using several strategies (one at a time), and look at the changes it suggests.
2. Create new test compartments and policies in your tenancy with no real resources.  This way, you can 
run either API simulations or test policy consolidations in a place where no resources exist. 
3. Clean up first - identify unnecessary statements and remove them and start a consolidation effort from a clean slate.
4. Use the Historical Comparison and multiple caches (by date loaded), and perform a consolidation, test the results,
compare history, and run for a while before doing additional consolidation.

