# Policy Graph desktop prototype and 7.0 dev-release checklist

Planning snapshot: 2026-10-13, branch `feat/7.0.0-policy-corpus-cross-tenancy`.

## Implementation update (2026-10-13)

Subsequent user refinements: desktop details now open from table right-click
(macOS Control-click also supported), with Enter/Space retained for keyboard
access. The extra Focus graph node dropdown was removed. Both interfaces now
use complete principal facets and suggestions across matching result pages,
just like effective paths. Context help was shortened to fit two lines. The
desktop graph scrollbar layout was intentionally left unchanged for review.

Following that review, the visible desktop graph scrollbars were removed;
wheel/trackpad scrolling remains. Initial guidance is passive, and graphical
search waits for two text characters or a selected filter. Right-click now
offers a menu item named **Show Detailed Analysis**, rather than immediately
opening the modal. Native Tk smoke verification and 15 graph tests passed.

The 2026-10-14 refinement removes the note below the graph and result pagination.
Both interfaces now show all matching grants, with a vertically scrollable
desktop table and a web table capped at 420 pixels. A Conditional column shows
Yes/No; details preserve the full expression. Right-click conditional rows to
send the expression to the existing Condition Tester. Default API callers retain
bounded pages; the graphical search interfaces explicitly request all results.

The local branch is now `feature/7.0.0-policy-corpus-cross-tenancy`, matching the
existing workflow and release branch patterns. The Policy Graph tab is
implemented beside Policy Analysis, using the shared graph service, Canvas
lanes with independent effective-path scrolling, keyboard node selection,
paged results, modal details, and load/reset/settings integration. It remains
available for policy-only CIS loads because it searches parsed corpus grants
without requiring a complete IAM inventory.

Verification: 27 focused tests passed; desktop/web result parity is covered.
A native macOS Tk check passed initial placeholders, 21 matching paths with
12 paged grants, permission search, node filtering, 151-permission details,
font/resize handling, and reset. Ruff passes for the new tab/tests and changed
desktop entry point. The full suite has 503 passing tests and the same two
pre-existing failures listed below. Manual user review, supported-platform
packaged checks, release notes, and commit/push remain. No deployment or
commit was performed.

## Target behavior

Add a `Policy Graph` desktop tab matching the current web graphical search. Use
`PolicyGraphService` directly with `app.app_context.corpus`; no HTTP server,
additional OCI requests, or separate policy interpretation is needed.

The only intentional interaction difference is a modal details popup in place
of the web drawer. The graph visualizes direct grants; it does not expand
inherited grants or claim that conditions and denies have been evaluated.

## Prototype implementation

1. Create `presentation/desktop/policy_graph_tab.py` as a `BaseUITab`. Use the
   web title and byline, context help, standard font settings, and documentation
   link. Place the tab beside Policy Analysis.
2. Provide Principal, Resource or permission, Effective path, Policy or
   statement, and Effect filters, plus Clear filters and Refresh view. Debounce
   text changes with Tk `after` at 300 ms; Enter applies immediately. Pass the
   same service arguments as web, including `overview=True`. Refresh view reads
   the current in-memory corpus.
3. Draw three lanes with native Tk Canvas primitives: Principals, Resources &
   Permissions, and Effective Paths. Show the same examples/placeholders until
   a filter is entered. Use the existing cross-tenancy Canvas drawing patterns
   for wrapped cards, tagged clicks, resize handling, and scrolling, without
   importing its tenancy-specific logic.
4. Keep grants bounded to 12 per page. Show every matching effective path from
   the service's `paths` result, independently of grant pagination, in a
   scrollable right lane with counts across all pages. Draw connections only
   between visible cards. Long names wrap without changing the stored key.
5. Match web click behavior: principal cards set Principal; path cards set
   Effective path; middle cards set Resource or permission to the resource and
   set Effect. Preserve other filters and return to page 1. Graph clicks only
   filter; they do not open details. Retain keyboard access through focusable
   lane selectors/buttons alongside the Canvas.
6. Add the same paged result table: Principal, Effect, Resource, Effective path,
   Policy, and Permissions count. Row selection/activation opens a modal
   `Toplevel` using the desktop's existing window conventions. Show policy
   name/OCID, original statement, statement ID, principal, effect, resource,
   path, and condition; put the complete permission list last in a scrollable
   area. Support Escape and restore focus to the table on close.
7. Wire construction, notebook registration, settings propagation, post-load
   updates, dataset reset, and limited-mode availability in `main.py`. Read the
   current corpus on refresh rather than retaining a service bound to an old
   dataset. Close stale details and reset to page 1 when the dataset changes.
8. Update desktop usage documentation and verify resource packaging requires
   no new dependency or external graph library.

## Acceptance checks

- Identical web and desktop result IDs, full permission lists, totals, path
  counts, and page boundaries for identical service inputs.
- Resource and permission searches are case-insensitive substring searches;
  `OBJECT_CREATE` and `object_` work and preserve all permissions of a matched
  grant. Combine these searches with principal/path/effect filters.
- Initial and cleared views show three examples rather than arbitrary grants.
- Searching `network` discovers a path whose grant is beyond page 1; selecting
  it focuses the results.
- Graph clicks change filters; only table rows open modal details.
- Original statement case is preserved; canonical principal keys do not create
  duplicate principals from domain-name case differences.
- Test long paths, at least 150 permissions, dense paths, empty results,
  unloaded corpus, reload/reset, keyboard navigation, resizing, and font sizes.
- Run focused service/controller tests and Ruff, then a real macOS Tk smoke
  and visual check. Check packaged desktop artifacts on supported OSes through
  the release workflow.

## Current release gaps

This is based on repository evidence and the current conversation, not a claim
that a complete original 7.0 requirements list has been recovered.

- The shared regular corpus, separate cross-tenancy corpus/projection, updated
  permissions analysis, cross-tenancy desktop Canvas, MCP search contract,
  consolidated operations, optional pinned-PyPI build, and image metadata are
  implemented. User acceptance of the newest graph behavior is in progress.
- The regular Policy Graph desktop prototype is implemented and ready for user
  testing. This is an addition to the saved cross-tenancy plan, which explicitly
  deferred the regular corpus visual view.
- The 2026-10-14 pre-commit run has 513 passing tests and no failures. The two
  previous failures are fixed. A regression reproduces and prevents duplicate
  desktop intelligence execution during Recommendations population. Saved
  strategy/risk settings are applied in the first post-load pass.
- The saved cross-tenancy implementation context still calls for dense live
  and cached desktop visual review and supported-platform executable checks.
- Latest graph and principal-normalization edits are local, beyond the last
  deployed combined image. Build/deploy those edits if testing the live service.
- `CHANGELOG.md` now includes the 7.0 dev-release notes. The run guide's
  stale legacy-variable paragraph has been corrected: `OPA_VERSION` is used
  only by the explicit PyPI build path; `DOCKER_CONTEXT` remains unused.
- Project structure, full lint, changed/new-file pre-commit hooks, whitespace,
  tests, and wheel/sdist builds pass. Generated parser exclusions cover current
  and legacy locations for both lint and format; pre-commit uses the validated
  Ruff version. The commit file list excludes local `.env`, credentials,
  generated deployment state, and build outputs. Commit/push remain.
- The branch has been renamed to `feature/*`, matching both
  `.github/workflows/build.yml` and `.releaserc.json`.
  Verify semantic-release will select the intended 7.0 prerelease; changing
  the local package version alone does not force its next version.
- PyPI publishing currently runs only on `main`. GitHub executable release
  attachment now also runs on `feature/*`, creating prerelease installers after
  the packaged startup checks pass. Feature pushes do not publish to PyPI.

## Suggested order for today's dev release

The desktop prototype and pre-commit cleanup are implemented and verified.
Review the prepared changes, align the prerelease version behavior, and
commit/push through the established release workflow. A successful push alone
is not evidence that desktop artifacts or a published dev release were produced;
verify the resulting CI artifacts and release version.
