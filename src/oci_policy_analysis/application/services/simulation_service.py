"""Service facade for policy simulation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.common.logger import get_logger


@dataclass
class SimulationPrepareResult:
    """Result payload returned by simulation context preparation."""

    principal_key: str
    required_where_fields: list[str]


class SimulationService:
    """Expose simulation operations without UI coupling."""

    def __init__(self, context: AppContext) -> None:
        """Initialize the simulation service.

        Args:
            context: Shared application context.

        Returns:
            None
        """
        self.context = context
        self.logger = get_logger(component='simulation_service')

    def prepare(
        self, *, compartment_path: str, principal_type: str, principal: object | None
    ) -> SimulationPrepareResult:
        """Prepare simulation context for a principal/compartment pairing.

        Args:
            compartment_path: Target compartment path.
            principal_type: Principal type value expected by simulation engine.
            principal: Principal object used for context resolution.

        Returns:
            SimulationPrepareResult: Principal key and required where-fields.
        """
        self.logger.info(
            'Preparing simulation context: compartment=%s principal_type=%s',
            compartment_path,
            principal_type,
        )
        engine = self.context.simulation
        principal_key, required_where_fields = engine.get_required_where_fields_for_context(
            compartment_path, principal_type, principal
        )
        return SimulationPrepareResult(
            principal_key=principal_key,
            required_where_fields=sorted(required_where_fields),
        )

    def run(
        self,
        *,
        principal_key: str,
        compartment_path: str,
        api_operation: str,
        where_context: dict[str, Any],
        checked_statement_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a policy simulation and record decision details.

        Args:
            principal_key: Resolved simulation principal key.
            compartment_path: Effective path used for simulation.
            api_operation: API operation being evaluated.
            where_context: Resolved where-clause context values.
            checked_statement_ids: Optional set of specific statement IDs to evaluate.

        Returns:
            dict[str, Any]: Simulation output payload.
        """
        self.logger.info(
            'Running simulation: principal_key=%s compartment=%s api_operation=%s',
            principal_key,
            compartment_path,
            api_operation,
        )
        engine = self.context.simulation
        return engine.simulate_and_record(
            principal_key=principal_key,
            effective_path=compartment_path,
            api_operation=api_operation,
            where_context=where_context,
            checked_statement_ids=checked_statement_ids,
        )
