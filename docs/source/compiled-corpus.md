# Compiled Corpus (experimental)

Launch the desktop application with `oci-policy-analysis-ui --experimental-features`
to show the **Compiled Corpus** tab. It does not require GenAI credentials.

Load policy data as usual, then select **Build Compiled Corpus**. Compilation runs
in the background with progress and cancellation. The previous successful snapshot
remains available if a rebuild fails or is cancelled.

## Build diagnostics and logging

The **Corpus logging** selector on the tab controls the `compiled_corpus`
component across snapshot capture, compilation, evaluation, and the tab itself.
It defaults to **INFO** unless a component level is configured. Changes apply
immediately, including during a build, without changing other component levels.
The application's existing `--verbose` override forces DEBUG and the selector
reflects that effective level.

Select **View Logs** to open **Build & Evaluation Logs**:

- **INFO** shows the five build stages (capture, compile, index, verify, publish),
  elapsed times, statement/grant counts, unresolved inputs, evaluation summaries,
  and invalidation events.
- **DEBUG** adds snapshot field types, per-statement source IDs and compilation
  details, scenario context-field requirements, and contribution witnesses.
- Failures include the traceback. Unsupported snapshot values identify the
  affected inventory field. Live and cached OCI SDK domain models are serialized
  as structured data.

The tab log view includes DEBUG output and retains a bounded recent history.
Logs also propagate to the normal shell/file handlers (`app.log`). The existing
Console tab continues to show INFO and above. **Clear Log View** clears only the
display. Context values are not dumped by the corpus diagnostic messages.

## Inspect the result

**Explore Corpus** displays principal, target subtree, permission, allow/deny
effect, condition kind, and source count. Filter by principal, scope, or permission.
Results are paged in groups of 250. Select a grant to inspect its complete condition
tree and every contributing statement ID and policy source. Identical grants share
one row; distinct condition alternatives remain separate rows.

Use **Add Filter** to combine field-specific constraints. Fields include principal,
scope, permission, effect, condition, conditional (`yes`/`no`), resource, verb,
policy name, statement ID, and source ID. Choose **contains**, **equals**,
**not contains**, or **not equals** for each row. Matching is case-insensitive;
all nonblank filters combine with AND, alongside the general search box.
**Apply Filters** or Enter applies them; **Clear Filters** restores the full list.
The count shows matching grants out of the complete corpus.

For example, combine principal contains `Finance`, scope equals `root/finance`,
permission contains `BUCKET`, and effect equals `allow`. Resource, verb, policy,
and source filters must all match the same supporting statement; attributes from
different duplicate sources are not combined to produce a false match. Grant
details still show all supporting provenance.

## Missing permission reference mappings

**Missing Permission Mappings** provides a deduplicated checklist grouped by
resource + verb + allow/deny effect. Each row shows affected statement and policy
name counts. Select it to see the original statements, IDs, and policy metadata.
**Export Missing Mappings** saves the full checklist and affected source records
as JSON so you can work through the permission library additions.

New diagnostics and INFO messages include the actual resource, verb, and effect:

```text
Resource/verb permission expansion is unknown: resource='example-family', verb='read', effect='allow'.
```

The checklist can also recover those fields from source provenance when opening
older corpora that contain only the generic error message. Missing expansions are
checked before condition/principal validation so those errors do not hide library
gaps. Unknown expansions do not produce permission grants; use this checklist to
find them rather than searching only the compiled grant rows. After updating the
reference JSON files, reload reference data (or restart the application), then
rebuild the corpus.

**Context & Coverage** shows input counts, unresolved statements, required context
variables, and model limitations. Unsupported inputs are retained, never silently
discarded. The initial compiler handles local statements using the application's
permission mappings and condition grammar. It does not prove full OCI equivalence,
perform general predicate implication, or synthesize replacement policies.

**Export Corpus** saves a versioned JSON artifact containing the semantic grants,
conditions, provenance, input snapshot, and reference data. **Open Corpus** restores
it for inspection. Rebuild against loaded data before evaluating an opened artifact.

The corpus is a snapshot. Changes to loaded policies, identities, hierarchy, or
reference data invalidate evaluation. Load/reset hooks invalidate immediately; a
background check detects in-place changes, and evaluation checks again before and
after execution. Changes made directly in OCI become visible after reloading OCI
data into the application. Prospective simulation statements are not included in
this first version.

## Write manual scenarios

1. Open **Manual Scenarios** and enter shared context as a JSON object, for example:

   ```json
   {
     "request.region": "iad",
     "request.utc-timestamp": "2026-09-11T12:00:00Z"
   }
   ```

2. Select or type a principal key, API operation, and target compartment path.
   Give the request a name and optionally an expected outcome.
3. Select **Find Relevant Context**. The form lists variables referenced by the
   candidate grants for this request. `request.permission` is bound for each
   permission check; `request.operation` comes from the selected operation.
4. Choose a mode for each field:
   - **Shared / unknown:** inherit the shared value, otherwise leave it unknown.
   - **Value:** supply a request-specific string (including an empty string).
   - **Absent:** explicitly set null, overriding any shared value.
5. Select **Add Request**. Repeat or select a saved request and use **Update
   Selected**. Changes to the editor take effect in the suite only after Add/Update.
6. Select **Run Scenarios**, or **Analyze Statement Contribution** to also measure
   the effect of removing individual source statements. Save/open suites as JSON.

Deny candidates add two explicit analysis assumptions to the context form:
`corpus.deny_enabled` and `corpus.deny_exempt`, each using the string `true` or
`false`. These describe tenancy deny enablement and whether the selected principal
is exempt. They are local model inputs, not OCI request variables. Without the
necessary assumptions, applicable deny behavior is indeterminate.

Each request retains its resolved context in the result. Shared values are copied
and overridden independently; one request cannot alter another's context. A missing
value is different from known absence. Unresolved inputs or unverified inventory
can make the overall result indeterminate even when the supported subset produces
a modeled allow/deny result. Related-resource checks remain advisory.

## Read contribution results

Results distinguish operation decision changes from permission changes. A statement
can contribute permission while an operation still fails for another reason.
Statements are also marked exercised, not exercised, or indeterminate. The JSON
result includes removal witnesses and links to source records through source IDs.

No measured effect is evidence about this suite, not proof that a statement can
never matter. Two duplicate statements can each be individually redundant while
removing both would change access. This feature does not remove policies.

## Example artifacts

The repository's `context/examples/` directory contains a small synthetic example:

- `compiled-corpus.json`: six source statements compiled into five symbolic grants.
- `corpus-scenarios.json`: six manual requests with shared region/time context.
- `corpus-results.json`: outcomes and individual statement-removal witnesses.

The example includes regional alternatives, duplicate inspect grants, inherited
scope, a time condition, and a conditional deny. It contains no live tenancy data.
Open the corpus to explore its shape; use the accompanying JSON files to understand
suite and result formats.

### Resource aliases and API identity

Permission resource entries (and families) may declare an `aliases` array, for
example `"aliases": ["instance"]` on `instances`. The catalog currently declares
`instance` → `instances` and `object` → `objects`. Aliases use the canonical
resource's cumulative permissions, risk and family/source information. Other
singular/plural forms are not inferred. Conflicting alias definitions fail
validation. Original statement text and IDs remain in corpus provenance.

Select **OCI API / catalog group** before selecting an operation in desktop
simulation, web simulation, or the compiled corpus scenario editor. The current
group is the permission JSON filename stem; some files combine multiple OCI APIs,
so this is a catalog namespace rather than a complete inventory of OCI endpoints.
For example, `bastion:CreateSession` and `generative_ai_agents:CreateSession` retain
separate permission requirements. Conditions receive the bare `CreateSession`
value in `request.operation`, which is bound by the evaluator.

New operation selections use qualified identities in saved scenarios and traces.
Legacy bare names (including `oci:`-prefixed names) resolve when unique; ambiguous
names produce an error listing the qualified choices. Edit those scenarios to
select the intended catalog group. Changes to the permission catalog, including
aliases or operation mappings, require a corpus rebuild just like policy changes.
