"""Semantic and lifecycle checks for the experimental compiled corpus."""

import json
from threading import Event
from types import SimpleNamespace

import pytest
from oci_policy_analysis.application.core.engine.compiled_corpus import (
    BuildCancelled,
    CorpusRuntime,
    build_corpus,
    capture_inputs,
)
from oci_policy_analysis.application.core.repo.policy_analysis_repository import PolicyAnalysisRepository
from oci_policy_analysis.application.services.compiled_corpus_service import CompiledCorpusService


def statement(sid, permissions=('READ',), condition='', effect='allow', scope='root/finance'):
    return {
        'internal_id': sid,
        'policy_name': 'Example',
        'statement_text': f'Source {sid}',
        'subject_type': 'group',
        'subject': [('Default', 'Readers')],
        'action': effect,
        'permission': list(permissions),
        'conditions': condition,
        'effective_path': scope,
    }


def context(statements):
    repo = PolicyAnalysisRepository()
    repo.regular_statements = statements
    repo.inventory_complete = True
    repo.identity_loaded_from_tenancy = True
    ref = SimpleNamespace(
        data={
            'resources': {},
            'families': {},
            'operations': {
                'oci:Read': {'permissions': ['READ']},
                'oci:Write': {'permissions': ['WRITE']},
                'oci:Both': {'permissions': ['READ', 'WRITE']},
            },
        }
    )
    return SimpleNamespace(policy_repo=repo, reference_data=ref)


def runtime(statements):
    ctx = context(statements)
    return CorpusRuntime(build_corpus(capture_inputs(ctx.policy_repo, ctx.reference_data)))


def scenario(**kwargs):
    return {
        'name': 'Read',
        'principal_key': 'group:Default/Readers',
        'api_operation': 'oci:Read',
        'compartment_path': 'root/finance',
        'context': {},
        **kwargs,
    }


def test_duplicate_sources_and_safe_counterfactuals():
    rt = runtime([statement('a'), statement('b')])
    assert len(rt.corpus['grants']) == 1
    assert len(rt.corpus['grants'][0]['source_ids']) == 2
    suite = rt.run_suite({'scenarios': [scenario()]}, contribution=True)
    assert suite['results'][0]['result'] == 'allowed'
    assert all(s['decision_changes'] == 0 for s in suite['statement_contribution'].values())
    assert rt.evaluate(scenario(), excluded=set(rt.corpus['sources']))['result'] == 'denied'


def test_or_alternatives_and_shared_overrides_are_independent():
    rt = runtime([statement('a', condition="request.region='iad'"), statement('b', condition="request.region='phx'")])
    assert len(rt.corpus['grants']) == 2
    suite = {
        'shared_context': {'request.region': 'iad'},
        'scenarios': [
            scenario(),
            scenario(context={'request.region': 'phx'}),
            scenario(context={'request.region': 'elsewhere'}),
        ],
    }
    results = rt.run_suite(suite, contribution=True)
    assert [r['result'] for r in results['results']] == ['allowed', 'allowed', 'denied']
    assert suite['shared_context'] == {'request.region': 'iad'}
    assert all(s['decision_changes'] == 1 for s in results['statement_contribution'].values())


def test_missing_absent_and_three_valued_boolean():
    rt = runtime([statement('a', condition="any { request.region='iad', !request.networkSource.name }")])
    assert rt.evaluate(scenario())['result'] == 'indeterminate'
    assert rt.evaluate(scenario(context={'request.region': 'iad'}))['result'] == 'allowed'
    assert rt.evaluate(scenario(context={'request.networkSource.name': None}))['result'] == 'allowed'
    assert (
        rt.evaluate(scenario(context={'request.region': 'phx', 'request.networkSource.name': 'vpn'}))['result']
        == 'denied'
    )


def test_permission_binding_operation_and_scope_boundaries():
    rt = runtime([statement('a', ('READ', 'WRITE'), "all {request.permission='READ', request.operation='Read'}")])
    assert (
        rt.evaluate(scenario(context={'request.permission': 'WRITE'}, compartment_path='root/finance/child'))['result']
        == 'allowed'
    )
    assert rt.evaluate(scenario(api_operation='oci:Write'))['result'] == 'denied'
    assert rt.evaluate(scenario(compartment_path='root/finance-other'))['result'] == 'denied'
    assert rt.evaluate(scenario(api_operation='unknown'))['result'] == 'indeterminate'


def test_deny_requires_assumptions_and_changes_decision():
    rt = runtime([statement('a'), statement('d', effect='deny')])
    assert rt.evaluate(scenario())['result'] == 'indeterminate'
    shared = {'corpus.deny_enabled': 'true', 'corpus.deny_exempt': 'false'}
    suite = rt.run_suite({'shared_context': shared, 'scenarios': [scenario()]}, contribution=True)
    assert suite['results'][0]['result'] == 'denied'
    denied_source = next(sid for sid, source in rt.corpus['sources'].items() if source['statement_id'] == 'd')
    assert suite['statement_contribution'][denied_source]['decision_changes'] == 1
    assert rt.evaluate(scenario(), {**shared, 'corpus.deny_exempt': 'true'})['result'] == 'allowed'


def test_unresolved_sources_and_partial_inventory_never_claim_complete_decisions():
    rt = runtime([statement('good'), statement('bad', condition="sets-equal(target.policy.type, 'allow')")])
    assert rt.corpus['summary']['unresolved_statements'] == 1
    assert rt.evaluate(scenario())['result'] == 'indeterminate'
    assert rt.evaluate(scenario())['modeled_result'] == 'allowed'
    assert len(rt.corpus['sources']) == 2


def test_capture_excludes_invalid_statements_but_keeps_them_in_the_policy_browser_repository():
    valid = statement('valid')
    invalid = {
        **statement('invalid'),
        'parsed': False,
        'valid': False,
        'invalid_reasons': ['ANTLR syntax error'],
    }
    ctx = context([valid, invalid])

    captured = capture_inputs(ctx.policy_repo, ctx.reference_data)
    corpus = build_corpus(captured)

    assert [item['internal_id'] for item in ctx.policy_repo.regular_statements] == ['valid', 'invalid']
    assert [item['internal_id'] for item in captured['inventory']['regular_statements']] == ['valid']
    assert corpus['summary']['statements'] == 1
    assert corpus['summary']['unresolved_statements'] == 0


def test_no_condition_parsing_during_queries(monkeypatch):
    rt = runtime([statement('a', condition="request.region in ('iad','phx')")])
    monkeypatch.setattr(
        'oci_policy_analysis.application.core.engine.compiled_corpus._parse',
        lambda _: pytest.fail('Query reparsed a condition'),
    )
    for region in ('iad', 'phx'):
        assert rt.evaluate(scenario(context={'request.region': region}))['result'] == 'allowed'


def test_user_membership_resolution():
    ctx = context([statement('a')])
    ctx.policy_repo.groups = [{'domain_name': 'Default', 'group_name': 'Readers', 'group_ocid': 'ocid1.group.readers'}]
    ctx.policy_repo.users = [{'domain_name': 'Default', 'user_name': 'Alice', 'groups': ['ocid1.group.readers']}]
    rt = CorpusRuntime(build_corpus(capture_inputs(ctx.policy_repo, ctx.reference_data)))
    assert rt.evaluate(scenario(principal_key='user:Default/Alice'))['result'] == 'allowed'
    assert rt.evaluate(scenario(principal_key='user:Default/Bob'))['result'] == 'denied'


def test_round_trip_and_order_independent_decisions():
    statements = [statement('a'), statement('b', ('READ', 'WRITE'))]
    first, second = runtime(statements), runtime(list(reversed(statements)))
    reopened = CorpusRuntime(json.loads(json.dumps(first.corpus)))
    for operation in ('oci:Read', 'oci:Write', 'oci:Both'):
        request = scenario(api_operation=operation)
        assert (
            first.evaluate(request)['permissions']
            == second.evaluate(request)['permissions']
            == reopened.evaluate(request)['permissions']
        )


def test_service_invalidates_for_policy_identity_and_reference_changes():
    ctx = context([statement('a')])
    service = CompiledCorpusService(ctx)
    old = service.build()
    ctx.policy_repo.regular_statements[0]['conditions'] = "request.region='iad'"
    with pytest.raises(ValueError, match='out of date'):
        service.run_suite({'scenarios': [scenario()]})
    assert service.get_corpus() == old
    service.build()
    ctx.policy_repo.groups.append({'group_name': 'New'})
    assert not service.check_current()
    service.build()
    ctx.reference_data.data['operations']['oci:Read']['permissions'] = ['WRITE']
    assert not service.check_current()


def test_failed_and_cancelled_rebuild_keeps_previous_snapshot():
    service = CompiledCorpusService(context([statement('a')]))
    previous = service.build()
    cancel = Event()
    cancel.set()
    with pytest.raises(BuildCancelled):
        service.build(cancel=cancel)
    assert service.get_corpus() == previous
    changed = False

    def progress(*args):
        nonlocal changed
        if not changed and 'Compiling statement' in args[-1]:
            service.context.policy_repo.regular_statements.append(statement('new'))
            changed = True

    with pytest.raises(ValueError, match='changed during'):
        service.build(progress=progress)
    assert service.get_corpus() == previous


def test_open_saved_corpus_requires_rebuild():
    service = CompiledCorpusService(context([statement('a')]))
    saved = service.build()
    service.open_corpus(saved)
    assert service.stale
    with pytest.raises(ValueError, match='out of date'):
        service.run_suite({'scenarios': [scenario()]})


def test_permission_change_without_operation_change_is_preserved():
    rt = runtime([statement('read-only')])
    result = rt.run_suite({'scenarios': [scenario(api_operation='oci:Both')]}, contribution=True)
    contribution = next(iter(result['statement_contribution'].values()))
    assert result['results'][0]['result'] == 'denied'
    assert contribution['permission_changes'] == 1
    assert contribution['decision_changes'] == 0


def test_unsupported_condition_object_is_not_an_unconditional_grant():
    rt = runtime([statement('bad', condition={'unsupported_shape': "request.region='iad'"})])
    assert rt.corpus['grants'] == []
    assert rt.corpus['summary']['unresolved_statements'] == 1


def test_reference_expansion_and_deny_inversion():
    ctx = context(
        [
            dict(statement('allow'), permission=[], resource='buckets', verb='read'),
            dict(statement('deny', effect='deny'), permission=[], resource='buckets', verb='manage'),
        ]
    )
    ctx.reference_data.data['resources'] = {
        'buckets': {'verbs': {'inspect': ['INSPECT'], 'read': ['READ'], 'use': ['WRITE'], 'manage': ['DELETE']}}
    }
    model = build_corpus(capture_inputs(ctx.policy_repo, ctx.reference_data))
    assert {(g['permission'], g['effect']) for g in model['grants']} == {
        ('INSPECT', 'allow'),
        ('READ', 'allow'),
        ('DELETE', 'deny'),
    }


def test_input_mutation_during_evaluation_discards_results():
    service = CompiledCorpusService(context([statement('a')]))
    service.build()

    def progress(*_):
        service.context.policy_repo.regular_statements[0]['permission'] = ['WRITE']

    with pytest.raises(ValueError, match='changed during evaluation'):
        service.run_suite({'scenarios': [scenario()]}, progress=progress)


def test_deny_unknown_assumptions_and_missing_context_are_visible():
    rt = runtime([statement('a'), statement('d', effect='deny')])
    result = rt.evaluate(scenario())
    denied_source = next(sid for sid, source in rt.corpus['sources'].items() if source['statement_id'] == 'd')
    assert denied_source in result['unknown_sources']
    rt = runtime([statement('a', condition="request.region='iad'")])
    assert rt.evaluate(scenario())['missing_context'] == ['request.region']
    assert rt.evaluate(scenario(context={'request.permission': 'spoofed'}))['resolved_context'] == {
        'request.operation': 'Read'
    }


def test_snapshot_serializes_sdk_domains_from_live_and_cache_loads():
    from datetime import UTC, datetime

    from oci.identity.models import Domain
    from oci.util import to_dict

    ctx = context([statement('a')])
    domain = Domain(
        id='ocid1.domain.example',
        display_name='Example',
        url='https://example.invalid',
        time_created=datetime(2026, 9, 11, tzinfo=UTC),
    )
    ctx.policy_repo.identity_domains = [domain]
    service = CompiledCorpusService(ctx)
    corpus = service.build()
    saved_domain = corpus['inputs']['inventory']['identity_domains'][0]
    assert saved_domain == to_dict(domain)
    assert saved_domain['id'] == 'ocid1.domain.example'
    assert saved_domain['time_created'].startswith('2026-09-11')
    assert service.check_current()
    assert isinstance(json.loads(json.dumps(corpus))['inputs']['inventory']['identity_domains'][0], dict)
    # Equivalent plain dictionaries and SDK objects must fingerprint identically.
    ctx.policy_repo.identity_domains = [to_dict(domain)]
    assert service.check_current()
    ctx.policy_repo.identity_domains[0]['display_name'] = 'Renamed'
    assert not service.check_current()


def test_snapshot_unknown_types_report_the_field_without_stringifying_objects(caplog):
    import logging

    ctx = context([statement('a')])
    ctx.policy_repo.identity_domains = [object()]
    with caplog.at_level(logging.INFO, logger='oci-policy-analysis.compiled_corpus'):
        with pytest.raises(TypeError, match='Snapshot field identity_domains: Unsupported snapshot value: object'):
            CompiledCorpusService(ctx).build()
    assert 'Snapshot capture started' in caplog.text
    assert any(r.exc_info and 'Corpus build failed' in r.message for r in caplog.records)


def test_build_logging_stages_debug_details_and_monotonic_progress(caplog):
    import logging

    service = CompiledCorpusService(context([statement('a')]))
    progress = []
    with caplog.at_level(logging.INFO, logger='oci-policy-analysis.compiled_corpus'):
        service.build(progress=lambda done, total, message: progress.append((done / total, message)))
    for stage in (
        'Snapshot capture started',
        'Snapshot capture completed',
        'Compilation started',
        'Compilation completed',
        'Runtime indexing started',
        'Runtime indexing completed',
        'Validating build inputs',
        'Corpus build published',
    ):
        assert stage in caplog.text
    assert not any(r.levelno == logging.DEBUG for r in caplog.records)
    assert [p[0] for p in progress] == sorted(p[0] for p in progress)
    assert progress[-1][0] == 1
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger='oci-policy-analysis.compiled_corpus'):
        service.build()
        service.run_suite(
            {'shared_context': {'request.region': 'private-value'}, 'scenarios': [scenario()]}, contribution=True
        )
    assert 'Snapshot field=identity_domains' in caplog.text
    assert 'Compiling source=' in caplog.text
    assert 'Scenario 1:' in caplog.text
    assert 'Contribution scenario=1' in caplog.text
    assert 'private-value' not in caplog.text


def test_tab_component_control_and_thread_safe_log_handler():
    import logging
    from threading import Thread

    from oci_policy_analysis.application.core.support.logger import get_logger
    from oci_policy_analysis.presentation.desktop.compiled_corpus_tab import CompiledCorpusTab, _CorpusLogHandler

    class Variable:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    root = logging.getLogger()
    logger = get_logger('compiled_corpus')
    other = get_logger('unrelated_component')
    previous = (root.level, logger.level, other.level)
    handler = _CorpusLogHandler()
    logger.addHandler(handler)
    fake_tab = SimpleNamespace(log_level=Variable('DEBUG'), app=SimpleNamespace(settings={}))
    try:
        root.setLevel(logging.WARNING)
        CompiledCorpusTab._set_log_level(fake_tab)
        assert logger.getEffectiveLevel() == logging.DEBUG
        assert root.level == logging.WARNING and other.level == previous[2]
        worker = Thread(target=lambda: logger.debug('worker detail'))
        worker.start()
        worker.join()
        assert any('worker detail' in handler.records.get_nowait() for _ in range(handler.records.qsize()))
        fake_tab.log_level.set('INFO')
        CompiledCorpusTab._set_log_level(fake_tab)
        assert not logger.isEnabledFor(logging.DEBUG)
        assert fake_tab.app.settings['log_levels']['compiled_corpus'] == 'INFO'
        # Existing --verbose behavior remains authoritative and the selector reflects it.
        root.setLevel(logging.DEBUG)
        fake_tab.log_level.set('WARNING')
        CompiledCorpusTab._set_log_level(fake_tab)
        assert fake_tab.log_level.get() == 'DEBUG'
        for _ in range(5100):
            logger.debug('bounded detail')
        assert handler.records.qsize() == 5000
        assert handler.dropped > 0
    finally:
        logger.removeHandler(handler)
        handler.close()
        root.setLevel(previous[0])
        logger.setLevel(previous[1])
        other.setLevel(previous[2])


def test_missing_mapping_diagnostics_group_by_resource_verb_and_effect():
    from oci_policy_analysis.application.core.engine.compiled_corpus import missing_permission_mappings

    ctx = context(
        [
            dict(statement('a'), resource='new-resource', verb='read'),
            dict(statement('b'), resource='NEW-RESOURCE', verb='READ'),
            dict(statement('deny', effect='deny'), resource='new-resource', verb='read'),
            dict(statement('manage'), resource='new-resource', verb='manage'),
            dict(statement('bad-condition', condition='unsupported syntax'), resource='other-resource', verb='use'),
        ]
    )
    corpus = build_corpus(capture_inputs(ctx.policy_repo, ctx.reference_data))
    assert corpus['grants'] == []
    for diagnostic in corpus['diagnostics']:
        assert diagnostic['code'] == 'unknown_permission_expansion'
        assert diagnostic['resource'] in diagnostic['message']
        assert diagnostic['verb'] in diagnostic['message']
        assert diagnostic['statement_id']
    rows = missing_permission_mappings(corpus)
    assert rows == corpus['missing_permission_mappings']
    assert len(rows) == 4
    row = next(r for r in rows if (r['resource'], r['verb'], r['effect']) == ('new-resource', 'read', 'allow'))
    assert row['statement_count'] == 2
    assert row['statement_ids'] == ['a', 'b']
    assert row['policy_names'] == ['Example']
    assert len(row['source_ids']) == 2


def test_old_generic_diagnostics_produce_the_same_mapping_checklist():
    from oci_policy_analysis.application.core.engine.compiled_corpus import missing_permission_mappings

    rt = runtime([dict(statement('a'), resource='missing-family', verb='manage')])
    expected = rt.corpus['missing_permission_mappings']
    rt.corpus['diagnostics'] = [
        {'source_id': d['source_id'], 'message': 'Resource/verb permission expansion is unknown.'}
        for d in rt.corpus['diagnostics']
    ]
    del rt.corpus['missing_permission_mappings']
    assert missing_permission_mappings(rt.corpus) == expected


def test_multiple_grant_filters_combine_and_support_exact_and_negative_matches():
    from oci_policy_analysis.application.services.compiled_corpus_service import filter_corpus_grants

    rt = runtime(
        [
            statement('a', ('READ', 'WRITE'), "request.region='iad'"),
            statement('b', ('READ',)),
            statement('d', ('READ',), effect='deny'),
        ]
    )
    filters = [
        {'field': 'principal', 'operator': 'contains', 'value': 'READERS'},
        {'field': 'scope', 'operator': 'equals', 'value': 'ROOT/FINANCE'},
        {'field': 'permission', 'operator': 'equals', 'value': 'read'},
        {'field': 'effect', 'operator': 'not equals', 'value': 'deny'},
        {'field': 'conditional', 'operator': 'equals', 'value': 'yes'},
        {'field': 'condition', 'operator': 'contains', 'value': 'request.region'},
        {'field': 'principal', 'operator': 'not contains', 'value': 'admins'},
    ]
    matches = filter_corpus_grants(rt.corpus, query='finance read', filters=filters)
    assert len(matches) == 1
    assert matches[0]['permission'] == 'READ'
    assert len(filter_corpus_grants(rt.corpus, filters=[])) == 4
    assert (
        filter_corpus_grants(rt.corpus, filters=[{'field': 'permission', 'operator': 'equals', 'value': 'REA'}]) == []
    )
    assert (
        len(filter_corpus_grants(rt.corpus, filters=[{'field': 'permission', 'operator': 'contains', 'value': 'REA'}]))
        == 3
    )
    assert filter_corpus_grants({}, filters=[]) == []


def test_source_filters_must_match_one_supporting_statement():
    from oci_policy_analysis.application.services.compiled_corpus_service import filter_corpus_grants

    ctx = context(
        [
            dict(statement('a'), resource='first-resource', verb='inspect', policy_name='First'),
            dict(statement('b'), resource='second-resource', verb='read', policy_name='Second'),
        ]
    )
    ctx.reference_data.data['resources'] = {
        'first-resource': {'verbs': {'inspect': ['READ']}},
        'second-resource': {'verbs': {'inspect': [], 'read': ['READ']}},
    }
    corpus = build_corpus(capture_inputs(ctx.policy_repo, ctx.reference_data))
    assert len(corpus['grants']) == 1
    filters = [
        {'field': 'resource', 'operator': 'equals', 'value': 'first-resource'},
        {'field': 'verb', 'operator': 'equals', 'value': 'read'},
    ]
    assert filter_corpus_grants(corpus, filters=filters) == []
    filters[1]['value'] = 'inspect'
    assert len(filter_corpus_grants(corpus, filters=filters)) == 1
    assert (
        len(
            filter_corpus_grants(
                corpus,
                filters=[
                    {'field': 'statement_id', 'operator': 'equals', 'value': 'b'},
                    {'field': 'policy_name', 'operator': 'equals', 'value': 'Second'},
                ],
            )
        )
        == 1
    )


def test_qualified_operation_binds_bare_request_operation_and_distinct_permissions():
    ctx = context([statement('one', condition="request.operation = 'CreateSession'")])
    ctx.reference_data.data['operations'] = {
        'bastion:CreateSession': {'api_name': 'bastion', 'operation_name': 'CreateSession', 'permissions': ['READ']},
        'agents:CreateSession': {'api_name': 'agents', 'operation_name': 'CreateSession', 'permissions': ['WRITE']},
    }
    ctx.reference_data.data['ambiguous_operations'] = {
        'CreateSession': ['bastion:CreateSession', 'agents:CreateSession']
    }
    rt = CorpusRuntime(build_corpus(capture_inputs(ctx.policy_repo, ctx.reference_data)))
    result = rt.evaluate(scenario(api_operation='bastion:CreateSession'))
    assert result['modeled_result'] == 'allowed'
    assert result['resolved_context']['request.operation'] == 'CreateSession'
    assert rt.evaluate(scenario(api_operation='agents:CreateSession'))['modeled_result'] == 'denied'
    with pytest.raises(ValueError, match='Ambiguous API operation'):
        rt.evaluate(scenario(api_operation='CreateSession'))
