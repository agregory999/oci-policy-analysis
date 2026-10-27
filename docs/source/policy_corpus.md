# Understanding the policy corpus

A policy corpus is the application's compiled view of the policies you loaded.
It turns statements into permission facts that the Policy Graph, Permissions
Analysis, and simulation can use. Each fact keeps a link to its source statement,
so you can follow a result back to the policy that produced it.

The source snapshot and the corpus serve different purposes. The snapshot keeps
the collected statements, including invalid or unresolved ones. The corpus holds
the parts the application can represent as permissions, along with reasons for
excluding the rest.

**NOTE:** The policy corpus is not the real OCI IAM Policy Engine, but comes as close
to it as we can get using static information that this tool ships with.

## What it contains

Each permission fact records:

- The principal, such as a group, dynamic group, or service.
- The permission expanded from the statement's verb and resource type.
- The allow or deny effect and any condition.
- The grant's compartment path and its source policy and statement.

The corpus also includes inherited facts for descendants in the loaded compartment
hierarchy. These retain the original grant path. Contributions from separate
statements stay separate, even when they refer to the same permission.

Permission expansion uses the bundled [reference catalog](reference_catalog.md).
For example, a statement granting `use virtual-network-family` produces facts for
the permissions covered by that resource family and verb in the catalog.

## What it leaves out

Statements cannot contribute permission facts when they are explicitly invalid,
lack a usable principal or path, have an unsupported effect, or have no concrete
permission mapping. Exclusions retain the source details and the reason. The
original statements remain available in the policy inventory.

A fact is not a confirmed access decision. Conditions remain attached until a
request supplies values to evaluate them. Allow and deny contributions remain
separate. The corpus does not supply missing policies, identity data, or live
resource state, and its coverage depends on what was loaded and what the parser
and catalog support. An empty search therefore does not prove that OCI denies
access.

## How the graph and simulation use it

**Policy Graph** uses direct facts to connect principals, grants, permissions,
and compartment paths. Shared facts make those relationships searchable without
each interface interpreting the statements again. The graph preserves conditions
and source evidence; it does not display every inherited fact or evaluate a
request. See [Policy Graph usage](usage.md#policy-graph).

**Simulation** uses the same permission expansion for candidate statements, then
evaluates the selected statements against the request's scope and condition
values. It checks the resulting permissions against the selected API operation's
catalog requirements. Prospective statements are compiled separately, so you can
test changes without changing the loaded policies or OCI. See
[Simulation](simulation.md) for the workflow and result details.

## Cross-tenancy and reloads

Cross-tenancy analysis has a separate corpus of definitions, source statements,
relationships, and unresolved findings. A local relationship does not prove that
the remote tenancy has supplied the matching policy.

Corpora are rebuilt when data is loaded. They are runtime models, not additional
fields saved into your snapshot, and building them does not rewrite the source
cache. For implementation details, see
[Policy corpora in the architecture guide](architecture.md#policy-corpora).
