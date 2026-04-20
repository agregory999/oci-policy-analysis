##########################################################################
# CONTEXT_policy_tag_concepts.md
#
# Project-Specific Context: OCI Policy Tag Concepts & Data Sources
##########################################################################

## Purpose and Audience

This context document distills the core concepts, data sources, and
operational considerations for working with **tag-aware OCI IAM policy
conditions**. It is intended for engineers building analysis,
visualization, or authoring experiences (e.g., the Tag-based Access tab)
that need to:

- Surface the universe of tag namespaces/keys that can appear in `where`
  clauses.
- Explain the relationship between **defined**, **free-form**, and
  **standard (Oracle-managed)** tags.
- Reference the broader set of request/target variables that share the
  `request.*` / `target.*` namespace with tag variables.

The material below summarizes three key Oracle documentation sources and
extends them with actionable guidance for extracting tag metadata from a
tenancy.

## OCI Tag Fundamentals

### Defined Tags

- Created within a tag namespace and compartment by tenancy
  administrators.
- Each defined tag namespace owns a schema of keys; values are usually
  free-form strings but can be constrained by defined tag defaults or
  governance rules.
- Can be surfaced programmatically via IAM Tagging APIs or the OCI CLI
  (`oci iam tag-namespace list` / `oci iam tag list`).
- Best suited for policy authoring because they provide a predictable
  namespace/key vocabulary.

### Free-Form Tags

- Ad-hoc key/value metadata applied directly to resources without a
  predefined namespace schema.
- Keys are unique to each resource; there is no tenancy-wide catalog to
  query.
- IAM policies **can** reference free-form tags, but discoverability is
  low. Any tooling should emphasize that the caller must already know the
  relevant free-form key/value pairs.

### Standard (Oracle-Managed) Tags

- Documented in [Understanding Standard Tags][standard-tags].
- Delivered in the `Oracle-Tags` namespace with canonical keys such as
  `createdBy`, `createdOn`, `deletedBy`, `deletedOn`, and service-specific
  markers.
- Enabled by administrators via standard tag definitions; once enabled,
  Oracle services automatically apply the tag values.
- Helpful for policy conditions that need to distinguish Oracle-created
  resources (e.g., automation jobs, managed services).

## Policy Condition Mechanics

### Access-Type Prefixes

Policies evaluate where-clause variables along one of a few canonical
axes (per [Conditions Syntax][conditions-doc]):

- `request.principal.*` – attributes about the calling principal.
- `target.resource.*` – attributes about the resource being accessed.
- `target.compartment.*` / `request.principal.compartment.*` – compartment
  metadata used in cross-compartment rules.

The tag-aware variants follow the normalized structure:

```
<access_type>.tag.<namespace>.<key>
```

Examples:

- `request.principal.group.tag.Operations.Project`
- `target.resource.compartment.tag.Finance.CostCenter`

The project’s `TagConditionCollector` relies on this shape to recognize
tag comparisons and emit normalized `(access_type, namespace, key)`
triples.

### Other Common Where-Clause Variables

When presenting tag conditions alongside general policy variables, it is
useful to remember other frequently referenced properties (per
[General Variables for All Requests][general-variables]):

- `request.permission` – the evaluated permission string (verb + resource).
- `request.operation` – the specific API operation name (e.g., `UpdateInstance`).
- `request.id`, `request.time`, `request.region` – metadata about the
  current call.
- `target.resource.type`, `target.resource.id` – resource identifiers.
- `target.tenancy.id` and compartment lineage variables.

Providing these side-by-side reinforces the broader context in which tags
are evaluated.

## Building a Tenancy Tag Catalog

### CLI / API Path

1. **List Tag Namespaces**
   ```bash
   oci iam tag-namespace list \
     --compartment-id <root-tenancy-ocid> \
     --all
   ```

2. **List Tag Keys within a Namespace**
   ```bash
   oci iam tag list \
     --tag-namespace-id <namespace-ocid> \
     --all
   ```

3. **Persist Results**
   - Cache `(namespace, key, description, is_retired)` in the project’s
     reference data (e.g., `reference_data_repo`).
   - Optionally emit JSON/CSV for offline analysis or UI preload.

4. **Permissions & Regions**
   - Caller needs `inspect tag-namespaces` and `inspect tag-defaults` in
     the home region.
   - Tag namespaces are global within a tenancy; listing from the home
     region is sufficient.

### Refresh Strategy

- Defined tags change infrequently, so a daily or manual refresh cadence
  is sufficient for most tooling.
- Store the retrieval timestamp to inform users when cached namespaces or
  keys might be stale.
- Consider automatically reconciling with documentation-derived examples
  so policy builders always see both **real tenancy tags** and
  **canonical Oracle tags**.

### Free-Form Tag Discovery

- No API enumerates free-form keys globally. The only programmatic option
  is to inspect resource inventory (via Search Service or resource
  listings) and aggregate encountered free-form tags.
- Document this limitation so users understand why policy tooling cannot
  suggest arbitrary free-form keys.

## Leveraging Documentation Sources

### Conditions Syntax ([conditions-doc])

- Details boolean logic, `all {}` / `any {}` groupings, and operator
  semantics.
- Lists the access-type prefixes that support `.tag.` (request principal
  group/compartment, target resource/compartment).
- Provides pattern examples such as
  `all { target.resource.tag.Operations.Project = 'PhoenixExpansion' }`.

### General Variables ([general-variables])

- Enumerates the full variable matrix for `request.*`, `target.*`, and
  `iam.*` contexts.
- Clarifies string normalization (case sensitivity, quoting) relevant to
  the Condition parser.
- Useful for cross-linking when explaining why tag variables coexist with
  other request metadata.

### Standard Tags ([standard-tags])

- Lists built-in `Oracle-Tags` keys and their governance impact.
- Provides lifecycle behavior (e.g., `deletedOn` applied when a resource
  is terminated).
- Highlights tagging best practices (naming, compartment scope, defaults).

## Integration Notes for the Project

- **TagConditionCollector** already normalizes tag comparisons. The data
  gathered via CLI/API can pre-populate UI dropdowns or validation logic.
- **Reference Data Repo** could store tenancy-specific tag catalogs and
  differentiate them from documentation-sourced examples.
- **Tag-based Access Tab** can merge:
  1. Parsed tags discovered in existing policies.
  2. Defined namespaces/keys fetched from the tenancy.
  3. Oracle standard tags and documentation snippets for education.
- When presenting prospective statements, highlight whether a tag is
  tenancy-defined, Oracle-standard, or documentation-only to set user
  expectations.
- **Condition Tester Tab** (`ui/condition_tester_tab.py`) exposes
  `_extract_variable_names`, which walks the ANTLR parse tree and yields
  every variable reference in an arbitrary clause. This is a convenient
  starting point for enumerating the *full* set of where-clause elements
  (tags, request.* variables, target.* variables, etc.) observed across
  sample policies.
- **Prospective Statements Service Tests** (`test_prospective_statements_service.py`)
  contain curated policy snippets that can feed the same extractor to
  build example lists for documentation or UI previews.

## Educational UX Opportunities Across Tabs

The project can weave educational guidance directly into the three
primary touchpoints for where-clause authoring and testing:

1. **Tag-based Access Tab**
   - Promote a *Learning strip* above the overview tables with quick
     links to:
       - This context doc (`CONTEXT_policy_tag_concepts.md`).
       - Oracle’s condition syntax reference.
       - Standard tag documentation.
   - Add a *“Show Common Where Clauses”* toggle that opens a palette of
     curated examples (general + tag-based). Selecting an entry should:
       - Set the builder fields (access type, namespace/key, operator).
       - Offer explanatory text ("Why use this clause" + prerequisites).
   - When prospective tags are unavailable for a namespace/key, surface
     inline hints explaining whether the tag is defined in tenancy,
     Oracle-managed, or documentation-only.

2. **Condition Tester Tab**
   - Embed a context-help link near the clause entry labeled "Need
     inspiration? Explore common where-clause patterns" that navigates to
     the Tag-based Access palette.
   - Pre-populate the *Generate Inputs* section with sample values when a
     recognized template is loaded (e.g., tag-based equality should show a
     sample tag value).
   - Consider a drop-down history of tested clauses with tags indicating
     whether they came from templates or free-form entry, reinforcing
     experimentation.

3. **Prospective Statement Editor**
   - Expand the *Where Clause* selector with a fourth option: **Common
     Where Clauses**. This would:
       - Present a modal/palette combining **General** variables (request.*,
         target.*) and **Tag-based** entries.
       - Merge live tenancy data by grouping defined tags under their
         namespace hierarchy (compartment-aware).
   - For tag namespaces discovered in sub-compartments, mark entries with
     breadcrumb paths (e.g., `Finance/Projects/Analytics`) so authors know
     where the definition lives.
   - After selecting a template, auto-fill the builder’s tag controls and
     display an *educational blurb* (markdown-styled label) describing when
     to use the clause and governance considerations.

### Template Catalog Flow

1. **Source Aggregation**
   - Start with curated YAML/JSON describing canonical clauses (general +
     tag-based) with metadata: title, description, example values, linked
     documentation.
   - Augment dynamically with defined tags from the tenancy (grouped by
     namespace, compartment path) and Oracle standard tags.

2. **Distribution**
   - Expose the catalog through a shared helper (e.g.,
     `WhereClauseTemplateCatalog`) so Tag-based Access, Condition Tester,
     and Prospective Editor can request templates consistent with their UI.
   - Provide filtering hooks: access type, tag namespace, policy verb,
     etc.

3. **User Experience**
   - Selecting a template should both inject the clause and highlight
     guidance content ("What this clause evaluates", "Required variables",
     "Related docs").
   - Offer a *“Send to Condition Tester”* button within the palette so
     users can immediately prototype with simulated inputs.

This education-first approach keeps the tooling actionable while guiding
policy authors through best practices and tenancy-specific constraints.

## Future Enhancements

- Automate reconciliation of tag catalogs with policy analyses to spot
  unused or deprecated tags.
- Extend the CLI harvesting step to also gather **tag defaults** and
  **tagging work requests**, enabling insights into enforcement/gaps.
- Consider integrating the OCI Search Service to discover free-form tags
  used in practice, with clear permissions warnings.

## References

- [OCI IAM Policy Conditions Syntax][conditions-doc]
- [General Variables for All Requests][general-variables]
- [Understanding Standard Tags][standard-tags]

[conditions-doc]: https://docs.oracle.com/en-us/iaas/Content/Identity/policysyntax/conditions.htm
[general-variables]: https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/policyreference_topic-General_Variables_for_All_Requests.htm
[standard-tags]: https://docs.oracle.com/en-us/iaas/Content/Tagging/Concepts/understandingstandardtags.htm