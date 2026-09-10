from typing import Any, cast

from oci_policy_analysis.application.core.common.consolidation_helpers import (
    effective_path_segments_for_rewrite,
    rewrite_statement_location_clause,
    rewritten_location_for_target,
)


def test_rewrite_statement_location_clause_rewrites_compartment_token() -> None:
    original = 'allow group G to manage buckets in compartment ROOT:Finance where request.user.id = abc'
    rewritten, note = rewrite_statement_location_clause(
        original,
        'Finance:Apps',
        target_policy_path='ROOT/Finance',
    )

    assert 'in compartment Finance:Apps' in rewritten
    assert rewritten.endswith('where request.user.id = abc')
    assert note == 'NOTE: location changed to Finance:Apps when moved to policy at ROOT/Finance.'


def test_rewrite_statement_location_clause_no_compartment_clause_keeps_text() -> None:
    original = 'allow service objectstorage-us-phoenix-1 to read buckets in tenancy'
    rewritten, note = rewrite_statement_location_clause(
        original,
        'ROOT',
        target_policy_path='ROOT',
    )

    assert rewritten == original
    assert note == 'NOTE: location changed to ROOT when moved to policy at ROOT.'


def test_effective_path_segments_for_rewrite_root_policy_x_and_location_y_z() -> None:
    st = {
        'compartment_path': 'ROOT/X',
        'location': 'Y:Z',
        'effective_path': 'ROOT',
    }
    segs = effective_path_segments_for_rewrite(cast(Any, st), st.get('location', ''))
    new_loc = rewritten_location_for_target(segs, ['ROOT'])
    assert segs == ['ROOT', 'X', 'Y', 'Z']
    assert new_loc == 'X:Y:Z'


def test_effective_path_segments_for_rewrite_root_policy_x_y_and_location_y_z_dedupes_overlap() -> None:
    st = {
        'compartment_path': 'ROOT/X/Y',
        'location': 'Y:Z',
        'effective_path': 'ROOT',
    }
    segs = effective_path_segments_for_rewrite(cast(Any, st), st.get('location', ''))
    new_loc = rewritten_location_for_target(segs, ['ROOT'])
    assert segs == ['ROOT', 'X', 'Y', 'Z']
    assert new_loc == 'X:Y:Z'


def test_effective_path_segments_for_rewrite_root_policy_x_and_location_y() -> None:
    st = {
        'compartment_path': 'ROOT/X',
        'location': 'Y',
        'effective_path': 'ROOT',
    }
    segs = effective_path_segments_for_rewrite(cast(Any, st), st.get('location', ''))
    new_loc = rewritten_location_for_target(segs, ['ROOT'])
    assert segs == ['ROOT', 'X', 'Y']
    assert new_loc == 'X:Y'


def test_rewritten_location_for_target_is_case_insensitive_for_prefix_match() -> None:
    effective = ['root', 'lz1-top', 'application-cmp']
    target = ['ROOT']
    new_loc = rewritten_location_for_target(effective, target)
    assert new_loc == 'lz1-top:application-cmp'


def test_rewrite_compartment_id_consumes_the_complete_location_reference() -> None:
    ocid = 'ocid1.compartment.oc1..target'
    original = f"Allow dynamic-group hermes-compute-dg to use generative-ai-response in compartment id {ocid} where request.principal.type = 'instance' // retain comment"
    rewritten, _ = rewrite_statement_location_clause(original, 'scratch', target_policy_path='ROOT/scratch')
    assert (
        rewritten
        == "Allow dynamic-group hermes-compute-dg to use generative-ai-response in compartment scratch where request.principal.type = 'instance' // retain comment"
    )
