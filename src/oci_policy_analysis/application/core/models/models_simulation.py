##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# models_simulation.py
#
# Dedicated TypedDict models for policy simulation flows (UI + MCP).
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

from typing import Annotated, Literal, NotRequired, TypedDict  # noqa: UP035

# ================================
# Simulation Models
# ================================

# SimulationPrincipalType describes all valid principal types in simulation requests and results.
SimulationPrincipalType = Literal['group', 'user', 'dynamic-group', 'any-user', 'any-group', 'service']


class SimulationPrepareRequest(TypedDict):
    """Canonical input for simulation preparation.

    Used to obtain principal and where-clause context, never for actual simulation execution.
    """

    compartment_path: Annotated[str, 'Effective compartment path, e.g. "ROOT/Finance"']
    principal_type: Annotated[SimulationPrincipalType, 'Principal type for simulation']
    principal: Annotated[
        str | list[str | None],
        'String for "any-user"/"any-group"/"service"; [domain, name] for user/group/dynamic-group',
    ]


class SimulationPrepareResponse(TypedDict):
    """Output of simulation preparation.

    Provides required where fields and a standardized principal key.
    """

    required_where_fields: Annotated[list[str], 'All unique where clause variable names required for input']
    principal_key: Annotated[str, 'Principal key as calculated by engine (e.g., "user:Default/anita")']


class SimulationScenario(TypedDict):
    """Canonical input for a single simulation scenario.

    Batch-mode simulations use a list of these in SimulationBatchRequest.
    """

    compartment_path: Annotated[str, 'Effective compartment path']
    scenario_internal_id: NotRequired[Annotated[str, 'Optional scenario identifier for grouping related simulations']]
    scenario_name: NotRequired[Annotated[str, 'Optional human-readable scenario name']]
    principal_key: Annotated[str, 'Principal key, must be from preparation stage']
    api_operation: Annotated[str, 'API operation to simulate, e.g., "oci:ListBuckets"']
    where_context: Annotated[dict[str, str], 'Variable input mapping for required where fields']
    checked_statements: NotRequired[Annotated[list[str], 'Statement IDs (UI only, omit for MCP/server)']]


class SimulationBatchRequest(TypedDict):
    """Batch simulation request (multiplex multiple scenarios).

    Example::

        {
          "simulations": [
            { ... see SimulationScenario ... }
          ],
          "trace": true
        }
    """

    simulations: Annotated[list[SimulationScenario], 'List of simulation scenarios to run']
    trace: NotRequired[Annotated[bool, 'If true, include trace output in SimulationResult']]


class SimulationResult(TypedDict):
    """Canonical result for a single simulation scenario.

    All fields strictly correspond to engine outputs and are fully JSON-serializable.
    """

    result: Annotated[Literal['YES', 'NO'], "'YES' if API operation permitted, 'NO' if denied"]
    api_call_allowed: Annotated[bool, 'True if API op permitted']
    final_permission_set: Annotated[list[str], 'Permissions granted after simulation']
    required_permissions_for_api_operation: Annotated[list[str], 'Permissions required for op']
    missing_permissions: Annotated[list[str], 'Any permissions missing for full allow']
    related_permission_checks: NotRequired[
        Annotated[list[dict], 'Advisory related resource/permission checks for troubleshooting']
    ]
    failure_reason: Annotated[str, 'Reason for denial or error, empty if successful']
    scenario_internal_id: NotRequired[Annotated[str, 'Scenario identifier associated with this result']]
    scenario_name: NotRequired[Annotated[str, 'Scenario name associated with this result']]
    simulation_name: NotRequired[Annotated[str, 'Simulation name associated with this result']]
    trace_statements: NotRequired[Annotated[list[dict], 'Statement-by-statement trace, if trace=True']]


class SimulationBatchResponse(TypedDict):
    """Batch simulation output: result list, matches input scenario order."""

    results: Annotated[list[SimulationResult], 'Simulation result(s) for each scenario, in order']


# ================================
# Prospective (What-If) Statements Models
# ================================


class ProspectiveStatementInput(TypedDict, total=False):
    """Lightweight input model for defining a prospective (what-if) statement.

    These fields mirror the data used by the UI's prospective editor and
    are consumed by PolicySimulationEngine.set_prospective_statements.
    """

    compartment_path: Annotated[str, 'Effective compartment path, e.g. "ROOT/Finance"']
    description: Annotated[str, 'Human-readable label or purpose for this statement']
    statement_text: Annotated[str, 'Raw OCI policy statement text']


class ProspectiveStatementSummary(TypedDict, total=False):
    """Summarized view of a prospective statement for MCP/UI listing."""

    internal_id: Annotated[str | None, 'Engine-assigned internal id (prospective-*)']
    policy_name: Annotated[str | None, 'Display name used for this statement']
    compartment_path: Annotated[str | None, 'Effective compartment path for the statement']
    parsed: Annotated[bool | None, 'True if parse succeeded']
    valid: Annotated[bool | None, 'True if statement is considered valid']
    invalid_reasons: Annotated[list[str] | None, 'Reasons for invalid/parse failure if any']
    statement_text: Annotated[str | None, 'Original raw policy statement text']


class ProspectiveStatementResult(TypedDict, total=False):
    """Result of adding or validating a single prospective statement via MCP."""

    parsed: Annotated[bool, 'True if the statement parsed successfully']
    valid: Annotated[bool, 'True if the parsed statement is considered valid']
    invalid_reasons: Annotated[list[str], 'Reasons for invalid result, if any']
    internal_id: Annotated[str | None, 'Assigned internal id if added to engine; None on failure']
    normalized: Annotated[dict, 'Normalized statement payload from the policy normalizer (if valid)']
    message: Annotated[str, 'Human-readable summary of the parse/add outcome']
