"""Legacy compatibility shim for consolidation helper functions.

TODO(refactor-phase-5): Remove this shim after all imports migrate to
`oci_policy_analysis.application.core.common.consolidation_helpers`.
"""

from oci_policy_analysis.application.core.common.consolidation_helpers import (  # noqa: F401
    compartment_ancestors_including_self,
    effective_path_segments_for_rewrite,
    find_compartment_by_hierarchy_path,
    flatten_defined_tags,
    internal_id_to_statement,
    is_root_path,
    lca_compartment_ocids,
    lca_path,
    normalize_compartment_path_segments,
    now_iso,
    policy_statement_texts,
    policy_tag_maps,
    required_policy_compartment_for_candidates,
    resolve_policy_compartment_path,
    rewritten_location_for_target,
    statement_scope_compartment_ocid,
)

__all__ = [
    'now_iso',
    'flatten_defined_tags',
    'policy_tag_maps',
    'policy_statement_texts',
    'internal_id_to_statement',
    'statement_scope_compartment_ocid',
    'compartment_ancestors_including_self',
    'lca_compartment_ocids',
    'normalize_compartment_path_segments',
    'lca_path',
    'find_compartment_by_hierarchy_path',
    'resolve_policy_compartment_path',
    'is_root_path',
    'effective_path_segments_for_rewrite',
    'rewritten_location_for_target',
    'required_policy_compartment_for_candidates',
]
