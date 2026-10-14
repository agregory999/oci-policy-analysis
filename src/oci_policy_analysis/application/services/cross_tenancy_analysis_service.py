"""Shared cross-tenancy projection adapter for desktop and web consumers."""

from __future__ import annotations

from typing import Any

from oci_policy_analysis.application.core.cross_tenancy_corpus import CrossTenancyCorpus, CrossTenancyCorpusBuilder
from oci_policy_analysis.application.core.cross_tenancy_projection import CrossTenancyProjector


class CrossTenancyAnalysisService:
    """Project cross-tenancy sources and diagnostics for any consumer.

    Args:
        repo: Repository used when a precompiled corpus is unavailable.
        findings: Optional intelligence findings for a fallback build.
        corpus: Precompiled cross-tenancy snapshot to prefer over a fallback build.

    Attributes:
        repo: Repository used for legacy/fallback projection.
        findings: Findings associated with the fallback repository.
        corpus: Optional snapshot bound to this instance.

    Notes:
        Local relationships do not establish that matching remote policies exist.
        Construct a new service when the active snapshot changes.
    """

    _fallback_aliases = staticmethod(CrossTenancyProjector._fallback_aliases)

    def __init__(
        self,
        repo: Any,
        findings: list[dict] | None = None,
        corpus: CrossTenancyCorpus | None = None,
    ) -> None:
        self.repo = repo
        self.findings = findings or []
        self.corpus = corpus

    def get_analysis_payload(self) -> dict[str, Any]:
        """Return a detached cross-tenancy projection with diagnostics.

        Returns:
            dict[str, Any]: UI-neutral source/relationship projection and schema version.
            Builds a temporary corpus from the repository if no corpus was supplied.
        """
        corpus = self.corpus or CrossTenancyCorpusBuilder().build(self.repo, self.findings)
        return corpus.project()
