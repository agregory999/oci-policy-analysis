"""Policy-intelligence strategy for complete ancestor supersession."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oci_policy_analysis.application.core.analysis import SupersessionAnalyzer


@dataclass(frozen=True)
class SupersessionStrategy:
    """Populate policy-intelligence output with complete supersession findings."""

    strategy_id: str = 'supersession'
    display_name: str = 'Complete policy supersession'
    category: str = 'supersession'

    def run(self, repo: Any, overlay: dict, params: dict | None = None) -> None:
        """Run complete-supersession analysis and save its findings.

        Args:
            repo: Loaded policy repository.
            overlay: Mutable policy-intelligence output.
            params: Optional strategy parameters, accepted for protocol parity.
        """
        overlay['supersessions'] = SupersessionAnalyzer().analyze(repo)
