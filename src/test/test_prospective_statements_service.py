##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl/
#
# test_prospective_statements_service.py
#
# Unit tests for the ProspectiveStatementsService tenancy-scoped manager
# for prospective (what-if) policy statements.
##########################################################################

from __future__ import annotations

from typing import Any

from oci_policy_analysis.application.services.prospective_statements_service import (
    SETTINGS_KEY_PROSPECTIVE_BY_TENANCY,
    ProspectiveStatementsService,
)


class FakeEngine:
    """Lightweight stub of PolicySimulationEngine for testing.

    Tracks calls to set_prospective_statements and allows test cases to
    control the behavior of validate_prospective_statement.
    """

    def __init__(self) -> None:
        self.last_set_list: list[dict[str, Any]] | None = None
        self.validate_responses: dict[str, dict[str, Any]] = {}

    def set_prospective_statements(self, stmts: list[dict[str, Any]]) -> None:  # pragma: no cover - trivial
        self.last_set_list = list(stmts)

    def validate_prospective_statement(self, text: str) -> dict[str, Any]:
        # Return a canned response when provided, otherwise a default
        # parsed/valid result.
        return self.validate_responses.get(
            text,
            {
                'parsed': True,
                'valid': True,
                'invalid_reasons': [],
                'normalized': {'statement_text': text},
            },
        )


def _make_service_with_seed(
    initial_list: list[dict[str, Any]] | None = None,
) -> tuple[ProspectiveStatementsService, FakeEngine, dict]:
    """Helper to construct a service + fake engine + settings with seed data."""

    tenancy_ocid = 'ocid1.tenancy.oc1..testtenancy'
    settings: dict[str, Any] = {}
    if initial_list is not None:
        settings[SETTINGS_KEY_PROSPECTIVE_BY_TENANCY] = {tenancy_ocid: list(initial_list)}

    engine = FakeEngine()
    service = ProspectiveStatementsService(settings=settings, simulation_engine=engine, tenancy_ocid=tenancy_ocid)
    return service, engine, settings


def test_load_from_settings_creates_records() -> None:
    seed = [
        {
            'compartment_path': 'ROOT/Finance',
            'description': 'Finance what-if',
            'statement_text': 'Allow group Finance to use buckets in compartment Finance',
        },
        {
            # Missing description should be normalized to empty string
            'compartment_path': 'ROOT/IT',
            'statement_text': 'Allow group IT to manage instances in compartment IT',
        },
    ]

    service, _engine, _settings = _make_service_with_seed(seed)

    all_records = service.list_all()
    assert len(all_records) == 2
    # Order is not guaranteed, so use sets for checks
    paths = {r.compartment_path for r in all_records}
    descs = {r.description for r in all_records}
    texts = {r.statement_text for r in all_records}

    assert paths == {'ROOT/Finance', 'ROOT/IT'}
    assert 'Finance what-if' in descs
    assert '' in descs  # second record description normalized to empty string
    assert 'Allow group Finance to use buckets in compartment Finance' in texts
    assert 'Allow group IT to manage instances in compartment IT' in texts


def test_create_and_validate_and_update_text() -> None:
    service, engine, _settings = _make_service_with_seed([])

    rec = service.create('ROOT/Dev', 'Dev test', '')
    # Initially no text -> invalid/unparsed
    assert not rec.parsed
    assert not rec.valid

    text = 'Allow group Dev to use buckets in compartment Dev'
    # Override default engine response for this specific text
    engine.validate_responses[text] = {
        'parsed': True,
        'valid': False,
        'invalid_reasons': ['Some semantic issue'],
        'normalized': {
            'statement_text': text,
            'subject_type': 'group',
            'subject': [(None, 'Dev')],
        },
    }

    updated = service.validate_and_update_text(rec.id, text)
    assert updated.statement_text == text
    assert updated.parsed is True
    assert updated.valid is False
    assert updated.invalid_reasons == ['Some semantic issue']
    assert isinstance(updated.normalized, dict)
    assert updated.normalized.get('subject_type') == 'group'
    assert updated.normalized.get('principal_key') == 'group:Default/Dev'
    principals = updated.normalized.get('principals') or []
    assert principals and principals[0].get('principal_key') == 'group:Default/Dev'
    assert updated.effective_path == 'ROOT/Dev'


def test_replace_all_from_simple_list_and_persist() -> None:
    service, engine, settings = _make_service_with_seed(None)

    new_entries = [
        {
            'compartment_path': 'ROOT/HR',
            'description': 'HR what-if',
            'statement_text': 'Allow group HR to read instances in compartment HR',
        },
    ]

    service.replace_all_from_simple_list(new_entries)
    records = service.list_all()
    assert len(records) == 1
    rec = records[0]
    assert rec.compartment_path == 'ROOT/HR'
    assert rec.description == 'HR what-if'

    # Persist and push into engine; should update both engine and settings
    service.persist_and_push_to_engine()

    # Engine should have received the simple list
    assert engine.last_set_list is not None
    assert len(engine.last_set_list) == 1
    assert engine.last_set_list[0]['compartment_path'] == 'ROOT/HR'

    # Settings should reflect the same simple list under the tenancy key
    tenancy_ocid = service.tenancy_ocid
    by_tenancy = settings.get(SETTINGS_KEY_PROSPECTIVE_BY_TENANCY, {})
    assert tenancy_ocid in by_tenancy
    stored_list = by_tenancy[tenancy_ocid]
    assert isinstance(stored_list, list)
    assert len(stored_list) == 1
    assert stored_list[0]['description'] == 'HR what-if'


def test_validate_and_update_text_without_engine_marks_unvalidated() -> None:
    # Service with no engine should still accept text but mark as not validated
    tenancy_ocid = 'ocid1.tenancy.oc1..noengine'
    settings: dict[str, Any] = {}
    service = ProspectiveStatementsService(settings=settings, simulation_engine=None, tenancy_ocid=tenancy_ocid)

    rec = service.create('ROOT', 'NoEngine', '')
    updated = service.validate_and_update_text(rec.id, 'Allow group X to use buckets in tenancy')

    assert updated.statement_text.startswith('Allow group X')
    assert updated.parsed is False
    assert updated.valid is False
    assert updated.invalid_reasons  # should contain a message about engine not available
    assert updated.effective_path == 'ROOT'
