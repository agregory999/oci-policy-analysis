# Tag-Based Policy Search

For the broader navigation model, see the top-level [Usage](./usage.md) guide. That page explains where tag-based search sits relative to basic filters, resource principals, and workload identities.

Tag-based policy search uses parsed `where` clause data instead of raw `.tag.` text scanning when parsed data is available. Multiple values in one filter field are ORed. Multiple populated fields are ANDed. Tag filters can be combined with regular policy filters such as `verb`, `permission`, `resource`, `principal_keys`, and `effective_path`.

## Tag Condition Search

Use these filters to match parsed tag conditions:

- `tag_namespace`: tag namespace, such as `Operations`
- `tag_key`: tag key, such as `Environment`
- `tag_value`: right-side value, such as `Prod`
- `tag_operator`: operator, such as `=`, `!=`, `in`, or `not in`
- `tag_access_type`: raw IAM condition prefix, such as `target.resource`
- `tag_access_semantics`: normalized semantic type

When several tag fields are supplied, one parsed tag condition must satisfy all supplied fields. For example:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "tag_namespace": ["Operations"],
    "tag_key": ["Environment"],
    "tag_value": ["Prod"],
    "verb": ["use"],
    "resource": ["instances"]
  }
}
```

## Semantic Access Search

The service classifies Oracle tag condition families into semantic categories:

- `request.principal.group.tag.*`: `requestor_group_tag`
- `request.principal.compartment.tag.*`: `requestor_compartment_tag`
- `target.resource.tag.*`: `target_resource_tag`
- `target.resource.compartment.tag.*`: `target_compartment_tag`

In practical terms:

- `requestor_group_tag` means the caller is authorized because one of the caller's groups has the tag.
- `requestor_compartment_tag` means the caller is authorized because the caller's compartment has the tag.
- `target_resource_tag` means the target resource must already have the tag.
- `target_compartment_tag` means the target resource's compartment, including nested compartments, is evaluated for the tag.

Example:

```json
{
  "filters": {
    "tag_access_semantics": ["target_resource_tag"],
    "permission": ["INSTANCE_UPDATE"]
  }
}
```

Results include `tag_context_warnings`. For target resource tags, warnings call out create-permission and list/inspect caveats. For target compartment tags, warnings call out nested-compartment behavior.

## Operator Search

`tag_operator` filters the parsed operator for one tag condition. The desktop UI exposes the supported finite operator set:

- `=`
- `!=`
- `in`
- `not in`
- `>`
- `<`
- `>=`
- `<=`
- `before`
- `after`
- `between`

Most tag-based access policies use `=`, `!=`, `in`, or `not in`. The broader set is available because the condition grammar can parse more general IAM condition operators.

Example:

```json
{
  "filters": {
    "tag_namespace": ["Operations"],
    "tag_key": ["Environment"],
    "tag_operator": ["in"]
  }
}
```

## Condition Atom Terms

`condition_atom_terms` is intentionally broader than tag-condition search. It searches every parsed condition atom field: left side, right side, operator, value type, evidence kind, and subexpression. Values within `condition_atom_terms` are ORed.

Use it when you do not yet know whether the thing you are looking for is represented as a normalized tag condition, a non-tag condition, or the right side of a comparison.

```json
{
  "filters": {
    "condition_atom_terms": ["request.principal.group.tag.Team"]
  }
}
```

## Policy Metadata Tags

Policy object tags are separate from IAM statement tag conditions:

- `policy_tag`: searches freeform and defined policy tags
- `policy_defined_tag`: searches only defined policy tags
- `policy_freeform_tag`: searches only freeform policy tags

When a policy object matches these filters, its contained statements are returned, and the result still ANDs with other filters.

## MCP Examples

Use `policy_search` when combining tag filters with general policy search:

```json
{
  "mode": "advanced",
  "detail_level": "full",
  "filters": {
    "tag_namespace": ["Operations"],
    "tag_key": ["Environment"],
    "tag_value": ["Prod"],
    "verb": ["use"]
  }
}
```

Use `tag_based_policy_search` for guided tag queries:

```json
{
  "tag_access_semantics": ["target_resource_tag"],
  "tag_namespace": ["Operations"],
  "tag_key": ["Environment"],
  "resource": ["instances"],
  "limit": 25
}
```

## Web And Desktop

The web policy API accepts the same filter keys under `/filter/policies`. The tag-focused endpoint `/filter/policies/tag-based` returns the same matched statements plus tag summaries.

The desktop Tag-based Access tab uses the same parsed-condition service. Its filters map to the same namespace, key, value, operator, semantic access, policy tag, and atom-term fields.

The top-level [Usage](./usage.md) page covers how the tag-based workflow fits alongside resource principals, OKE workload identities, and other advanced filters.

A dedicated web UI page for tag-based access has not been built yet. The current web support is API-level plus statement-inspector fields. The recommended sequence is to settle the shared service and desktop semantics first, then mirror the stable desktop experience into web.

Legacy `conditions` substring search remains available for backward compatibility and for unparsed older rows, but parsed `tag_conditions` are the source of truth whenever present.
