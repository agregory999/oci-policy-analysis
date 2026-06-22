# Related Permission Checks

OCI APIs can return 404 or authorization-style failures even when the caller has
the direct permission for the selected operation. One common cause is a related
resource dependency. For example, moving a compute instance can also require
permission on an associated compute capacity reservation.

OCI Policy Analysis models these as **related permission checks**. They are
advisory troubleshooting hints, not live OCI inventory validation and not part of
the primary simulation allow/deny decision.

## How They Are Used

Related checks are attached to API operation reference data. When an operation is
selected in simulation or reference-data tools, the app can show:

- the primary permissions required by the selected operation;
- related resources that may also need to be checked;
- related permissions and operation names when known;
- when the relationship applies;
- a troubleshooting hint for 404 or authorization failures.

In simulation results, related checks are evaluated against the simulated final
permission set where possible. Missing related permissions are shown separately
from the operation's primary `missing_permissions`.

## Example

`ChangeInstanceCompartment` requires `INSTANCE_MOVE`. If the instance is
associated with a compute capacity reservation, the same principal may also need
`CAPACITY_RESERVATION_MOVE` on the related reservation.

That relationship is represented as reference metadata on the operation, not as a
hard simulation requirement, because the app may not know whether a specific
instance is attached to a reservation.

## Adding Relationships

Not every OCI operation has related checks. If you find a missing relationship,
open an issue or pull request with:

- the API operation name;
- the related resource type;
- the related permission or operation, if known;
- the condition under which it applies;
- a short source note or observed failure case.

The preferred implementation is a structured `related_checks` entry in the
appropriate permissions JSON file, with any longer narrative left in `notes`.
