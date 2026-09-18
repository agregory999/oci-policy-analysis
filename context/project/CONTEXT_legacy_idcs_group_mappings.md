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

## Planned replacement

The future identity-domain mapping API should load explicit mapping records and
materialize mapped aliases in the repository group model. Once it exists,
replace the validation-only bridge with that data. Do not infer mappings merely
from same-named groups in arbitrary domains.

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
