# Risk Scoring Context

## Purpose

Risk scoring is a ranking model for OCI IAM policy review. It is not an OCI authorization result, a probability of compromise, or an absolute loss estimate. The score is intended to help users compare statements and policies in the same loaded dataset.

## Statement Risk Formula

Statement raw risk is calculated as:

```text
raw_statement_risk = exposure_points * compartments_in_scope
adjusted_statement_risk = raw_statement_risk after optional reductions
```

`exposure_points` comes from the permission reference data:

| Verb tier | Per-permission exposure weight |
|---|---:|
| `inspect` | 1 |
| `read` | 5 |
| `use` | 50 |
| `manage` | 100 |

For a parsed statement with derived permissions, the engine sums the per-permission risk for the statement's permission list. For a statement without a permission list, the engine asks `ReferenceDataRepo.get_verb_resource_risk(verb, resource)`, which expands the verb/resource into cumulative permissions and sums their weights.

For unknown resources that are not in the reference data, the engine uses a conservative fallback:

```text
unknown_resource_exposure = base * verb_weight
```

`base` is `1` for a resource and `2` for a resource family name. Unknown resource exposure is capped at 10% of `manage all-resources` exposure so an unrecognized type does not outrank known tenancy-wide administrative access.

## Compartment Exposure

`compartments_in_scope` is the number of compartments at or below the statement effective path. The match is path-segment aware:

- `root/dev` matches `root/dev` and `root/dev/app`.
- `root/dev` does not match sibling prefixes such as `root/development`.

If the effective path is missing, the engine uses `1` and records that the path is unknown.

## Reductions

Where-clause reduction:

- Applied when a statement has parsed conditions.
- Default is controlled by settings (`risk_where_clause_reduction_pct`).
- Current allowed values are `0`, `25`, `50`, `75`, and `90`.
- This is a coarse discount for constrained access, not proof that the condition is safe.

Service-principal reduction:

- Applied to `service` subject statements with `use` or `manage` verbs.
- Default is controlled by settings (`risk_service_principal_reduction_pct`).
- Current allowed values are `0`, `25`, `50`, `75`, and `90`.
- This reflects that service principals are usually narrower than human or group principals, but it should not hide broad service grants.

## Policy Risk

Policy-level risk is aggregated from statement scores:

- `Max Score`: highest adjusted statement score in the policy.
- `Avg Score`: average adjusted statement score.
- `Total Raw Risk`: sum of adjusted statement scores.
- `Max Statement Risk (Global %)`: log-normalized relative rank of the policy's highest statement compared with the highest statement in the loaded dataset.

The relative percentage is for UI comparison only. Use `Score`, `Max Score`, and `Total Raw Risk` when comparing absolute model output.

## Known Limits

- The model assumes permission reference data is current and complete.
- Where clauses are discounted uniformly; the model does not yet score condition quality by atom type.
- Service-principal reductions are subject-type based and do not inspect the service's operational blast radius.
- Cross-tenancy trust and deny semantics may need separate scoring models.
- Scores are most meaningful within the same loaded dataset and settings profile.
