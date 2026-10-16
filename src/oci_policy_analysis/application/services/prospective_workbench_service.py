"""Snapshot-bound prospective orchestration shared by desktop evidence views."""

from copy import copy, deepcopy

from oci_policy_analysis.application.core.engine.policy_intelligence_engine import PolicyIntelligenceEngine
from oci_policy_analysis.application.services.prospective_statements_service import ProspectiveStatementsService


class ProspectiveWorkbenchService:
    """Bind persisted what-if records to the active context without changing sources.

    Args:
        context: Loaded AppContext; create a new facade after a snapshot load.

    Attributes:
        context: Current loaded runtime.
        records: Tenancy-scoped CRUD and persistence service shared with other adapters.

    Notes:
        Construction loads prospects once and hydrates simulation without writing
        caches. Risk calculations use a detached statement and repository view.
    """

    def __init__(self, context):
        """Reuse the current tenancy's manager and hydrate its simulation overlay."""
        self.context = context
        tenancy = str(context.policy_repo.tenancy_ocid or '').strip()
        if not tenancy:
            raise ValueError('Load a tenancy before editing prospective statements.')
        service = getattr(context, '_prospective_service', None)
        if service is None or service.tenancy_ocid != tenancy:
            service = ProspectiveStatementsService(
                cache_manager=context.cache,
                policy_repo=context.policy_repo,
                tenancy_ocid=tenancy,
                simulation_engine=context.simulation,
            )
            context._prospective_service = service
            context.simulation.set_prospective_statements(service.to_simple_list())
        self.records = service

    def statement_views(self) -> list[dict]:
        """Return detached, labelled prospects, including invalid source evidence.

        Returns:
            list[dict]: Statement-shaped records suitable for core search filters.
        """
        rows = []
        for raw in self.context.simulation.get_prospective_statements():
            row = {**deepcopy(raw.get('normalized') or {}), **deepcopy(raw)}
            row['policy_name'] = '[Prospective] ' + str(raw.get('policy_name') or 'What-if')
            row.setdefault('action', 'unknown')
            rows.append(row)
        return rows

    def potential_risk(self, record) -> dict | None:
        """Estimate risk with existing scoring over detached validated evidence.

        Args:
            record: Validated ProspectiveStatementRecord from this tenancy.

        Returns:
            dict | None: Score, notes and recommendations, or None if invalid.
                This heuristic does not evaluate conditions or establish OCI access.
        """
        if not record.parsed or not record.valid:
            return None
        repository = copy(self.context.policy_repo)
        statement = deepcopy(record.normalized or {})
        statement.update(internal_id=record.id, effective_path=record.effective_path or record.compartment_path)
        repository.regular_statements = [statement]
        engine = PolicyIntelligenceEngine(repository)
        engine.calculate_potential_risk_scores()
        return engine.overlay['risk_scores'][0]
