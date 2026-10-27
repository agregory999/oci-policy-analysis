# Reference catalog

The bundled JSON catalog maps OCI resource types and families to IAM verbs,
permission identifiers, and API operations. Entries also carry source links,
aliases, coverage notes, and related permission checks where available.

These mappings let the application expand a policy such as `use virtual-network-family`
into individual permissions, look up the permissions required by an API operation,
and suggest policy candidates during simulation. The [policy corpus](policy_corpus.md)
uses the catalog to build searchable permission facts from loaded statements.

Coverage varies by service. An operation can require permissions on several
resources, in different compartments, with additional checks depending on its
parameters. The catalog records known gaps; it does not replace OCI authorization.

The catalog is available through the MCP tools `resource_reference`,
`operation_reference` and `permission_reference`. See [MCP lookup examples](mcp.md#reference-discovery-and-reverse-lookup).
These tools do not require a loaded tenancy and keep catalog coverage separate
from snapshot coverage. Typed results retain mapping gaps, provenance and notes.

## Empty mappings are valid catalog entries

Keep recognized resources even when their permission or API-operation mapping is
unavailable. Do not manufacture permission identifiers to fill the gap.

| Case | Catalog representation | Interpretation |
| --- | --- | --- |
| Audit `inspect` | An empty verb increment | Oracle documents no permission at that verb |
| Audit `read` | `AUDIT_EVENT_READ`, covering `audit:ListEvents` | `use` and `manage` add no further permissions |
| Cloud Shell | `mapping_status: no_published_mapping`, empty `use` permissions, no API operations | The resource and `use cloud-shell in tenancy` policy are documented; named permission/API mappings are not supplied by the linked access guide |
| Work-request operations with inherited checks | `mapping_status: context_dependent`, empty fixed list plus explanatory notes | The spawning operation determines the requirements; an empty list cannot establish access |
| Explicitly public operations | Empty permissions with source notes stating no permissions are required | Different from a missing or context-dependent mapping |

See Oracle's [Audit reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/auditpolicyreference.htm)
and [Cloud Shell access guide](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/cloudshellintro.htm).
Cloud Shell still requires authorization, and commands executed inside it need
their own OCI policies. Removing the internal `UNKNOWN_PERMISSION_CLOUD_SHELL`
placeholder does not establish that a principal can use Cloud Shell.

## Reviewed corrections

The October 2026 review corrected source transcription and mapping discrepancies:

- Removed prose fragments such as `I`, `DRG`, and `T` from API permission lists,
  corrected IPSec permission spellings, and split joined Organizations permissions.
  Conditional source requirements remain in operation notes; flat lists do not
  express every alternative or parameter-dependent requirement.
- Reviewed Core networking permission increments and the DRG component tables
  against the [Core policy reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/corepolicyreference.htm).
  `drgs` remains the aggregate; `drg-object` identifies its individual object.
- Corrected OKE resource permission prefixes and verb placement using the
  [OKE reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/contengpolicyreference.htm).
  The documented aggregate is `cluster-family`; `container-engine-family` remains
  a legacy catalog lookup alias. Added the documented `cluster-pod-shapes` entry.
- Corrected registry permission increments against the
  [Registry reference](https://docs.oracle.com/en-us/iaas/Content/Identity/policyreference/registrypolicyreference.htm).
- Retained conditional database requirements using the
  [Base Database reference](https://docs.oracle.com/iaas/Content/Identity/Reference/dbsystempolicyreference.htm).
  Work-request and compartment-move checks that cannot be represented by a fixed
  permission list explicitly report their limitation instead of passing an empty check.

Source URLs and review notes are attached to affected entries. Where a retained
catalog key differs from the spelling in the source, `source_resource_name` and
declared aliases preserve the documented spelling. `search_terms` contains human
vocabulary such as “virtual machines”; these are discovery hints, not extra OCI
policy identifiers. This review does not validate every entry in every service.

## Remaining resource/verb coverage gaps

An API permission can be retained even when the catalog cannot map it back to a
resource and verb. Absence from the resource tables is a review signal, not proof
that the identifier is invalid. In particular, do not delete a source-documented
operation requirement just to make the tables agree.

The remaining review includes Core VTAP dependencies and maintenance-event
permissions, resource locks, IAM compartment/tag/work-request permissions,
Organizations transfer approval, OS Management Hub module streams, Logging
Analytics and ZPR topology checks. Some source pages themselves use differing
spellings: for example, `BACKUP_POLICY_INSPECT` in a resource table versus
`BACKUP_POLICIES_INSPECT` in the operation table. These require individual source
review; no replacement is inferred solely from similar spelling.

Regression checks reject malformed permission tokens and exercise the reviewed
mappings, declared aliases, explicit gaps and context-dependent operations.
They cannot prove that a syntactically plausible identifier is current or mapped
to the correct verb. Preserve provenance and inspect the linked service reference
when using results to design a policy.

## Snapshot compatibility

This changes bundled reference data and derived analysis, not the saved snapshot
format. Combined caches remain version 2/schema 3; supported older snapshots do
not need migration. Corpus compilation, permissions reports and simulation can
produce different results after loading the same snapshot with the corrected
catalog. Original policy text and input cache files are not rewritten. Rebuild
derived analysis after upgrading; do not compare old and new derived totals as
proof that OCI policies changed.
