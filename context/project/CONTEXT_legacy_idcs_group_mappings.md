# Legacy OracleIdentityCloudService Group Mapping

## Current compatibility behavior

Some converted OCI tenancies retain an identity domain named
`OracleIdentityCloudService` (IDCS). OCI allows an unqualified policy group
reference such as `allow group ABC ...` to refer to an IDCS group named `ABC`,
even though the policy parser represents that reference as the `Default`
domain.

Until group mappings can be loaded from OCI, invalid-statement validation has a
narrow compatibility bridge in `PolicyIntelligenceEngine.find_invalid_statements`:

- It applies only when the policy group name is unqualified.
- It requires that `OracleIdentityCloudService` is present in the loaded
  identity-domain inventory.
- It accepts the statement only when a same-named group exists in that domain.
- Explicitly qualified domains, ordinary `Default` groups, dynamic groups,
  simulation, policy filtering, consolidation, and principal keys are not
  changed.

## Live-tenancy mapping inventory

For live tenancy loads, the repository now best-effort discovers the SAML2
identity provider named `OracleIdentityCloudService` and calls
`list_idp_group_mappings` for it. Mapping records are held separately in
`idp_group_mappings` and are saved in combined caches. A missing permission or
API failure logs an informational message and does not fail the broader load.

Each active mapping records its IdP source-group name and resolved target IAM
group. The target group carries `mapped_idp_groups`, displayed as **Mapped IdP
Groups** when the Groups tab is in its expanded view. The JSON Debugger exposes
the raw inventory as **Policy Repo IdP Group Mappings**.

During validation, an otherwise unresolved unqualified group subject can be
resolved through an explicit mapping. Its statement receives a parsing note
showing `OracleIdentityCloudService/<source> -> Default/<target>`. Direct group
matches still take precedence, and mappings do not alter simulation,
consolidation, filtering, or principal keys.

## CIS Compliance snapshot assumption

CIS Compliance exports do not contain IdP group-mapping records. When a CIS
snapshot contains the `OracleIdentityCloudService` identity domain, the loader
sets a compliance-only flag and the invalid-statement check treats that domain
and `Default` as interchangeable for group and dynamic-group existence checks.
The desktop completion popup explicitly labels this as an assumption. It does
not affect simulation, policy filtering, consolidation, or principal keys, and
must be replaced by explicit mappings for a live tenancy.

## Regression expectations

- A naked group name resolves through this bridge only for the loaded legacy
  IDCS domain.
- The same group is invalid if the legacy domain itself is absent.
- A policy explicitly naming `Default` must not use the bridge.
