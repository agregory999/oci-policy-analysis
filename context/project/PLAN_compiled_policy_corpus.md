# Experimental compiled policy corpus

Status: initial experimental desktop implementation available on this branch.
The first version includes build/export/open, a paged grant explorer, context and
coverage diagnostics, manual suites with shared context, and source-removal
contribution analysis. General symbolic supersession and policy synthesis remain
future work. See `docs/source/compiled-corpus.md` and `context/examples/`.
Branch: `feature/compiled-policy-corpus`
Baseline: merged `github/main`, `52422c57` (2026-09-11).

Agreed scope: focus first on the inspectable corpus and an evaluation framework.
Retain statement IDs for provenance. Policy re-authoring and reapplication of
policy read/manage access remain later work; the initial corpus still includes
those permissions as part of the current authorization model.

## Recommendation

Build a symbolic authorization model that can be queried without consulting
original statement text, then use it as the input to a separate policy authoring
pass. This is a viable extension of simulation and the permissions report.
We have enough code and data structures to start; we do not yet have evidence
of complete tenancy context or full equivalence to OCI authorization.

“Compile” is a useful architectural analogy. This proposal does not assume
knowledge of OCI's private compiler, caches, or internal representation.

The original statements disappear from the decision model and primary view.
Retain an immutable source snapshot and a separate source map for explanation,
verification, and rollback. Removing statement boundaries from the semantic
model should not destroy evidence or original policy ownership metadata.

## Representation

Use a sparse graph/index rather than enumerating every user, permission,
resource, compartment, and possible request value.

```text
Corpus
  snapshot: tenancy, capture times, input hashes, completeness by capability
  semantics: compiler/schema versions, reference-data hash, feature settings
  principals: canonical identities, group relationships, symbolic selectors
  scopes: compartment OCIDs, ancestry, resource selectors
  predicates: typed expression DAG, required variables and applicability
  grants: principal selector × scope selector × permission × effect × predicate
  authoring constraints: attachment, ownership, original resource/verb intent
  diagnostics: unresolved, unsupported, missing inventory/reference mappings
  source map: semantic node → all contributing policy/statement source records
```

Use OCIDs where resolved, retaining names as labels and unresolved names as
explicit unresolved references. Keep group and dynamic-group selectors rather
than flattening them permanently into today's members. Workload/resource
principal identities must retain their complete predicates, including OR branches.
Keep subtree scope symbolic so inheritance also represents future descendants.

For a given principal, target, and permission, applicable allows combine with
OR; conditions within a rule preserve their ALL/ANY structure. Applicable denies
combine separately. For the supported ordinary case, the result is
`any_allow AND NOT any_deny`; OCI-specific exemptions and cross-tenancy rules
require explicit semantics rather than assuming that formula is universal.

Example: two grants for the same principal/scope/permission, conditional on
`region = A` and `region = B`, become one grant with predicate
`region = A OR region = B`, carrying both source references. They must never
collapse to an unconditional permission or a single “conditional” flag.

Distinguish symbolic conditions, missing snapshot knowledge, missing scenario
inputs, and variables known to be inapplicable to a request. A query may report
allowed, denied, conditional, or indeterminate with reasons; those are local
analysis statuses, not claims about OCI response codes. Unknown evidence must
not silently become false or make a rewrite appear equivalent.

## Existing foundations and gaps found in code

| Area | Available today | Compiler work |
| --- | --- | --- |
| Permissions | `ReferenceDataRepo.get_permissions` expands verbs/families, including deny inversion | Version mappings; diagnose unknown expansions; retain family/verb intent for future evolution |
| Report | `PolicyIntelligenceEngine.build_permissions_report` produces grant rows with source IDs and descendant expansion | Compile from parsed inputs; report lookup maps overwrite same-key condition/source metadata, and rows only retain a conditional flag plus source text |
| Conditions | ANTLR grammar, shared evaluator, display-oriented structure and atoms | Typed, lossless semantic AST/DAG with operator, literal, presence, set, pattern, and variable applicability semantics |
| Principals/scope | Repository membership filtering, principal keys, effective compartments | Audit canonical identity resolution; keep symbolic membership and scope; distinguish attachment from target scope |
| Simulation | Applicable-statement filtering, prospective policies, evaluation and traces | Evaluate compiled grants, bind `request.permission` per permission check, retain API-operation and target-specific context |
| Inventory | Snapshot flags and CIS capability metadata | Capability-level completeness and freshness manifest, including failures and unresolved external dependencies |
| Consolidation | Existing proposal/placement workflows and limits | Reuse presentation/export patterns after a semantic authoring and equivalence layer exists |

The current simulator evaluates a statement condition before expanding and
adding its permission set. That deserves a specific audit for conditions on
`request.permission`; matching existing simulation output alone is insufficient
evidence of correctness. Existing related API permission checks are advisory,
not a full multi-resource authorization model.

## Do we have the full context?

This review inspected source code, not a live tenancy snapshot. The first
deliverable should answer the following for the actual loaded corpus:

- Are all relevant policies, compartments, identity domains, memberships, and
  dynamic-group rules captured, with known collection failures and timestamps?
- Which resource/tag inventories and workload attributes are known, and which
  selectors require request-time inputs or remain symbolic?
- Are all resource families, permissions, API requirements, condition operators,
  and variable applicability rules represented by the reference data?
- Are cross-tenancy counterparts available? Local Define/Endorse/Admit text alone
  cannot establish the other tenancy's complete contribution.
- Is deny enablement known, and can the default-administrator exemption and
  relevant deny limitations be represented?
- Who should own/manage each generated policy, what placement/naming conventions
  apply, and what business purpose justifies the access?

Request-time values do not have to exist now to compile symbolic rules. They
do have to be supplied or modeled to decide a concrete request. Business intent
is different: existing access does not prove necessity or justify least-privilege
reductions. Usage evidence can inform proposals, but cannot by itself prove that
unused access will never be needed.

## Proposed phases

1. **Coverage and semantic contract.** Produce a corpus capability report and
   explicit support matrix. Account for every input statement as compiled,
   unresolved, or unsupported. Preserve excluded constructs as residual inputs;
   a partial compile must never be presented as the entire effective corpus.
2. **Compiler and export.** Add core models/compiler plus a thin application
   service. Export deterministic JSON with symbolic grants, predicates,
   provenance, coverage, and diagnostics. Begin with local allow/deny policies,
   supported predicates, and symbolic principal/scope selectors. Keep
   cross-tenancy constructs visible but unresolved until their model is ready.
3. **Explorer and evaluation.** Add an experimental view beside Simulation and
   Permissions Report: principal → scope → permission → granting/blocking
   predicates. Show required context, coverage, and all contributing sources.
   Support inverse permission-to-principal queries. Expose the same service to
   other interfaces after the model settles. Separate live and prospective
   snapshot identities; invalidate on policy, identity, hierarchy, reference,
   feature-setting, or relevant inventory changes.
4. **Conservative simplification.** Deduplicate exact semantic grants, share
   predicates, and remove grants only where implication is established in a
   supported fragment. Preserve all source mappings. Avoid unconstrained Boolean
   expansion; use shared DAG nodes and indexed candidate selection.
5. **Policy synthesis.** Generate a candidate corpus from the semantic model,
   under explicit placement and ownership constraints. Start with exact
   permission sets; use verbs/families only when their expansion and intended
   future behavior are acceptable. Apply tenancy policy/statement limits and
   language constraints. Preserve unsupported residuals unchanged and label
   output partial. Reuse the proposal workflow for reviewable output.
6. **Equivalence and explanation.** Reparse/recompile generated policies and
   compare grants, predicates, deny behavior, scope, and governance constraints.
   Produce added/lost access and unknown differences, with counterexamples
   where possible. Label structural proof separately from sampled regression
   evidence. Export human documentation with rationale, scope, ownership,
   conditions, provenance, and unresolved assumptions.

Recommended first implementation boundary: phases 1–3, with a small exact
deduplication preview. Defer full re-authoring until the model is inspectable.

## Compilation order and supersession analysis

Read statements in a deterministic order for reproducible builds and traces,
but make the resulting semantics independent of ingestion order. Record what
each statement adds to the partial corpus as a diagnostic only: this measures
contribution relative to a prefix, not redundancy in the complete corpus.

For example, an unconditional READ grant followed by an unconditional
READ+WRITE grant makes the second statement add WRITE. In the completed corpus,
the first statement is redundant. Reversing ingestion order changes the build
trace but must not change that conclusion.

After compilation, compare each statement's semantic contribution against the
union of the other contributions. Coverage must include principal selectors,
scope, permissions, effect, and predicates, not just permission names. Several
statements may collectively cover another even if no one statement does.
For supported predicate fragments, record proven containment and its supporting
source IDs; otherwise record an unresolved relationship with the reason.
Distinguish same-effect grant containment from end-to-end decision equivalence,
which also depends on denies, exemptions, and the rest of the corpus.

Preserve a many-to-many source relationship at the grant/predicate-alternative
level. A merged grant's flat list of statement IDs is insufficient to support
removing one source if each source contributed a different condition. Pair the
existing statement ID with snapshot identity, policy identity, source position,
and a content hash so IDs need not be assumed stable across reloads.

## Batch evaluation and statement contribution

Support hundreds or thousands of offline scenarios against one compiled
snapshot. Each scenario supplies a principal, operation, target compartment and
resource context, request attributes, and an optional expected outcome. Suite
manifests record snapshot/reference versions, assumptions, generation seed,
coverage goals, and unresolved dependencies. No live API invocation is required.

For each scenario, evaluate the baseline and track:

- Candidate statements reached through principal/scope/permission indexes.
- Predicate results, including true, false, missing inputs, and unsupported cases.
- Permissions granted or blocked and all contributing source alternatives.
- The final modeled operation decision and any unresolved related-resource checks.
- Counterfactual results with each relevant source statement disabled: changed
  permission results, changed operation decision, and a witness scenario.

Track permission-level changes separately from operation-level changes. A
statement can supply a needed permission while the operation still fails for a
different missing permission. Deny contributions are equally important: removing
a deny can enable access. Contribution is not a count of allowed operations.

Use separate evidence labels rather than one opaque usefulness score:

| Label | Evidence |
| --- | --- |
| Decisive in suite | Removing this source changes at least one modeled operation decision |
| Permission-contributing in suite | Removal changes permission results, possibly without changing an operation decision |
| Exercised but redundant in suite | It contributes matching grants/blocks, but removal changes neither measured result |
| Not exercised | The suite has no matching evidence for this source |
| Proven redundant in supported model | Symbolic comparison establishes removal equivalence within stated assumptions |
| Indeterminate | Missing context or unsupported semantics prevents a conclusion |

The labels can coexist across different scenarios; retain counts and witnesses.
Do not infer real-world usage from generated tests. A statement with no observed
effect is a review candidate, not automatically safe to remove.

Two identical statements illustrate a critical removal rule: each is individually
redundant while the other remains, but removing both can revoke access. Keep
alternative-support groups and re-evaluate every proposed removal against the
remaining corpus. Never turn individual no-effect findings into a bulk deletion
list without validating the resulting corpus.

Generate suites from API permission mappings, principal classes, compartment
boundaries, condition branches, satisfying/non-satisfying values, presence and
absence cases, and allow/deny interactions. Include hand-authored expected
outcomes; generated baselines alone cannot detect a shared semantic bug.
Arbitrary string, time, tag, and resource domains cannot be exhausted by a finite
suite. Scope any complete-coverage claim to an explicitly bounded modeled domain.

Report distinct coverage dimensions: input compilation, reference/API mapping,
principal/scope exercise, predicate branches, grant/block exercise, and
counterfactual contribution. Show denominators, exclusions, and unknowns. A
large test count alone is not evidence of meaningful coverage.

Begin with baseline plus source-removal evaluation over indexed candidate
statements. Cache predicate results within each scenario and reuse unaffected
grant nodes; do not reparse/recompile the corpus per removal. Benchmark before
promising throughput or adding more complex incremental machinery. Keep removal
overrides isolated from the immutable baseline snapshot.

## Re-authoring constraints

- **Equivalence versus improvement:** a clean equivalent rewrite preserves
  existing access, even if overly broad. Least-privilege changes should be
  explicit, separately reviewable changes with a stated rationale.
- **Placement:** moving a policy may preserve access to resources while changing
  who can edit/delete the policy. Preserve or explicitly approve that governance
  change; rewrite relative scope references correctly.
- **Future behavior:** replacing `manage <family>` with today's enumerated
  permissions may preserve today's snapshot but exclude future permissions.
  Flattening groups or compartment subtrees creates the same temporal problem.
  Retain symbolic intent and identify snapshot-only equivalence.
- **Comments:** generate policy descriptions and accompanying Markdown or IaC
  comments. Do not assume IAM statement strings support arbitrary inline comments.
  Explain mechanically derived behavior; label missing business rationale rather
  than inventing it.
- **Recoverability:** source text is not required for compiled decisions, but the
  source archive remains necessary when coverage is incomplete or a proposal
  needs to be explained/reversed.

## Validation and success criteria

Use existing tests/fixtures plus targeted cases for duplicate conditional grants,
nested ALL/ANY, missing versus inapplicable variables, unary presence, patterns
and sets, per-permission conditions, group overlap, workload selectors,
inheritance and sibling isolation, deny inversion/exemptions, partial inventory,
unknown mappings, and unresolved cross-tenancy policies.

For supported cases, compare interpreted and compiled decisions, then separately
validate documented OCI semantics so shared bugs are not treated as proof.
Check deterministic exports, complete source accounting, and compile/recompile
stability. For synthesis, test both added and lost access and future-selector
intent. Measure compilation size/time and repeated-query latency against existing
simulation using representative snapshots before claiming a performance benefit.

Success for the first milestone: one loaded corpus produces a useful searchable
semantic object; every grant can explain its conditions and evidence; every
unsupported input is visible; queries require no reparsing of source statements.

## OCI references checked for this proposal

- [Conditions](https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/conditions.htm):
  request applicability matters; an inapplicable variable makes a condition false.
- [Advanced policy features](https://docs.oracle.com/en-us/iaas/Content/Identity/Concepts/policyadvancedfeatures.htm):
  permission and operation conditions constrain otherwise broad grants.
- [Policy attachment](https://docs.oracle.com/en-us/iaas/Content/Identity/policieshow/Policy_Attachment.htm):
  attachment determines policy administration rights.
- [Cross-tenancy policies](https://docs.oracle.com/en-us/iaas/Content/Identity/policieshow/iam-cross-domain.htm):
  access requires cooperating policies in both tenancies.
- [Deny policies](https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/denypolicies.htm):
  opt-in feature, default-administrator exemption, precedence, and metaverb inversion.

## Feedback topics

1. Agreed: the first goal is an inspectable compiled corpus, including source
   provenance and batch evaluation of statement contribution.
2. Should equivalent authoring preserve policy-management ownership by default?
   Recommendation: yes, and show proposed ownership changes explicitly.
3. Should rewrites preserve symbolic future behavior of families, memberships,
   and compartment inheritance? Recommendation: yes; mark snapshot-only
   alternatives clearly when offered.
