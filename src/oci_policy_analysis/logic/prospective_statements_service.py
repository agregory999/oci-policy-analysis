##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl/
#
# prospective_statements_service.py
#
# Tenancy-scoped manager for prospective (what-if) policy statements.
#
# Centralizes CRUD, validation, and persistence for prospective policy
# statements so that both the UI (Simulation tab, Tag-based Access tab,
# future builders) and the MCP server can treat prospective statements as
# part of the tenancy data model rather than UI-owned state.
#
# Supports Python 3.12 and above
#
# @author: Cline AI
#
# coding: utf-8
##########################################################################

"""Prospective (what-if) policy statements service.

This module defines a small data model and a service class that manage
prospective policy statements on a per-tenancy basis. The service is
responsible for:

* Loading and persisting the per-tenancy prospective list from/to the
  shared settings structure used by the UI today
  (``simulation_prospective_statements_by_tenancy``).
* Providing a simple CRUD API over a normalized in-memory representation
  (:class:`ProspectiveStatementRecord`).
* Delegating validation of statement text to the
  :class:`~oci_policy_analysis.logic.simulation_engine.PolicySimulationEngine`
  via its ``validate_prospective_statement`` helper.
* Pushing the current list into the simulation engine using
  ``set_prospective_statements`` so that prospective statements are
  merged with real tenancy policies for simulation.

The simulation engine remains the single source of truth for how
prospective statements are normalized, merged, and evaluated during
simulation. This service simply orchestrates persistence and provides a
UI-friendly API.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.policy_intelligence import PolicyIntelligenceEngine

logger = get_logger(component='prospective_statements_service')


SETTINGS_KEY_PROSPECTIVE_BY_TENANCY = 'simulation_prospective_statements_by_tenancy'


@dataclass
class ProspectiveStatementRecord:
    """In-memory representation of a single prospective policy statement.

    This record is intentionally lightweight and UI-agnostic. It mirrors
    the per-tenancy list currently stored in settings and the
    :class:`PolicySimulationEngine`'s internal prospective representation,
    while adding a stable ``id`` field for UI selection and updates.

    Attributes:
        id: Stable identifier for this record (UUID string).
        tenancy_ocid: OCID of the tenancy this record belongs to.
        compartment_path: Hierarchy path where the statement would live
            (e.g. ``"ROOT/Finance"``).
        description: Human-friendly label for the statement.
        statement_text: Full OCI IAM policy statement text.
        parsed: Whether the statement text parsed successfully according
            to ``validate_prospective_statement``.
        valid: Whether the parsed statement passed semantic validation.
        invalid_reasons: Optional list of validation/parse issues.
        normalized: Optional normalized statement representation as
            returned by the simulation engine's validation helper.
    """

    id: str
    tenancy_ocid: str
    compartment_path: str
    description: str
    statement_text: str
    parsed: bool = False
    valid: bool = False
    invalid_reasons: list[str] = field(default_factory=list)
    normalized: dict[str, Any] | None = None
    effective_path: str | None = None


class ProspectiveStatementsService:
    """Tenancy-scoped manager for prospective policy statements.

    The service is designed to be constructed once per active tenancy and
    then shared across UI tabs and other callers via the main application
    object (e.g. ``app.prospective_service``).

    It intentionally does **not** implement any simulation or parsing
    logic itself; all validation and normalization are delegated to the
    :class:`PolicySimulationEngine`.
    """

    def __init__(self, settings: dict, simulation_engine: Any, tenancy_ocid: str):
        if not tenancy_ocid:
            raise ValueError('ProspectiveStatementsService requires a non-empty tenancy_ocid')

        self._settings = settings
        self._engine = simulation_engine
        self._tenancy_ocid = str(tenancy_ocid)
        # Internal mapping from record id -> ProspectiveStatementRecord
        self._records: dict[str, ProspectiveStatementRecord] = {}
        self._intelligence_engine_cache: PolicyIntelligenceEngine | None = None

        logger.info('ProspectiveStatementsService: initializing for tenancy %s', self._tenancy_ocid)
        self._load_from_settings()

    # ------------------------------------------------------------------
    # Public query helpers
    # ------------------------------------------------------------------

    @property
    def tenancy_ocid(self) -> str:
        """Return the tenancy OCID associated with this service."""

        return self._tenancy_ocid

    def list_all(self) -> list[ProspectiveStatementRecord]:
        """Return all known prospective statement records for this tenancy."""

        return list(self._records.values())

    def list_valid(self) -> list[ProspectiveStatementRecord]:
        """Return only parsed & valid prospective statement records."""

        return [r for r in self._records.values() if r.parsed and r.valid]

    def get(self, record_id: str) -> ProspectiveStatementRecord | None:
        """Return the record for ``record_id``, or ``None`` if missing."""

        return self._records.get(record_id)

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def create(
        self,
        compartment_path: str,
        description: str,
        statement_text: str,
    ) -> ProspectiveStatementRecord:
        """Create a new prospective statement record.

        The new record is added to the in-memory cache but is **not**
        automatically validated or persisted; callers should explicitly
        invoke :meth:`validate_and_update_text` and
        :meth:`persist_and_push_to_engine` as appropriate.
        """

        rec_id = str(uuid.uuid4())
        rec = ProspectiveStatementRecord(
            id=rec_id,
            tenancy_ocid=self._tenancy_ocid,
            compartment_path=(compartment_path or 'ROOT'),
            description=description or '',
            statement_text=statement_text or '',
        )
        self._records[rec_id] = rec
        logger.debug('ProspectiveStatementsService: created record %s at %s', rec_id, rec.compartment_path)
        return rec

    def upsert(self, record: ProspectiveStatementRecord) -> ProspectiveStatementRecord:
        """Insert or replace the given record in the in-memory cache."""

        if record.tenancy_ocid != self._tenancy_ocid:
            raise ValueError('Record tenancy_ocid does not match service tenancy_ocid')
        self._records[record.id] = record
        logger.debug('ProspectiveStatementsService: upserted record %s', record.id)
        return record

    def delete(self, record_id: str) -> None:
        """Remove the record with the given id, if present."""

        if record_id in self._records:
            logger.debug('ProspectiveStatementsService: deleting record %s', record_id)
        self._records.pop(record_id, None)

    def replace_all_from_simple_list(self, entries: Iterable[dict[str, Any]]) -> None:
        """Replace all records from a simple list structure.

        This helper is provided to ease transition from the existing
        SimulationTab UI, which works with a list of dictionaries in the
        following shape::

            {
                "compartment_path": "ROOT/Finance",
                "description": "My what-if policy",
                "statement_text": "Allow ...",
            }

        The method clears the current in-memory cache and recreates
        records from the provided list, without automatically validating
        or persisting them.
        """

        logger.info(
            'ProspectiveStatementsService: replacing all records from simple list (count=%d)',
            len(list(entries)),
        )

        # Convert entries to a list first so we can safely iterate twice
        # (for logging length and creation). This is expected to be small.
        entries_list = list(entries)

        # Build a new mapping but *reuse* existing records when ids
        # match so that parsed/normalized state is preserved across
        # saves. New rows without ids get fresh records.
        new_records: dict[str, ProspectiveStatementRecord] = {}

        for entry in entries_list:
            text = (entry.get('statement_text') or '').strip()
            if not text:
                # Skip completely empty rows; they are effectively
                # placeholders in the UI.
                continue

            rec_id = str(entry.get('id') or uuid.uuid4())
            existing = self._records.get(rec_id)

            if existing is not None and existing.tenancy_ocid == self._tenancy_ocid:
                prior_text = (existing.statement_text or '').strip()
                prior_comp = (existing.compartment_path or '').strip()
                # Update mutable fields on the existing record but keep
                # parsed/valid/invalid_reasons/normalized as-is so that
                # a prior Parse operation continues to apply until the
                # text is explicitly re-validated.
                existing.compartment_path = entry.get('compartment_path') or 'ROOT'
                existing.description = entry.get('description') or ''
                existing.statement_text = text
                existing.effective_path = entry.get('effective_path') or existing.effective_path

                # If the statement text or compartment path changed, any
                # previously derived parse/normalized/effective values are
                # stale and must be cleared so downstream engine pushes are
                # based on the new content.
                if prior_text != text or prior_comp != (existing.compartment_path or '').strip():
                    existing.parsed = False
                    existing.valid = False
                    existing.invalid_reasons = []
                    existing.normalized = None
                    existing.effective_path = entry.get('effective_path') or None
                rec = existing
            else:
                rec = ProspectiveStatementRecord(
                    id=rec_id,
                    tenancy_ocid=self._tenancy_ocid,
                    compartment_path=(entry.get('compartment_path') or 'ROOT'),
                    description=entry.get('description') or '',
                    statement_text=text,
                    effective_path=entry.get('effective_path'),
                )

            new_records[rec_id] = rec

        self._records = new_records

    # ------------------------------------------------------------------
    # Validation + persistence
    # ------------------------------------------------------------------

    def validate_and_update_text(
        self,
        record_id: str,
        new_text: str,
    ) -> ProspectiveStatementRecord:
        """Validate and update the statement text for a record.

        The statement text is updated in-place and then passed to the
        simulation engine's ``validate_prospective_statement`` helper so
        that parse/valid flags and invalid reasons can be surfaced in the
        UI.

        The engine remains responsible for the actual parsing and
        semantic checks; this service merely records the result.
        """

        rec = self._records[record_id]
        rec.statement_text = (new_text or '').strip()

        if not rec.statement_text:
            # Empty text is treated as not parsed/invalid, but we allow
            # the record to exist so users can fill it in later.
            rec.parsed = False
            rec.valid = False
            rec.invalid_reasons = []
            rec.normalized = None
            self._ensure_effective_path(rec)
            return rec

        engine = self._engine
        if engine is None or not hasattr(engine, 'validate_prospective_statement'):
            # Without a simulation engine, we cannot validate, but we keep
            # the text so it can be validated later.
            logger.info(
                'ProspectiveStatementsService: simulation engine missing; skipping validation for record %s',
                record_id,
            )
            rec.parsed = False
            rec.valid = False
            rec.invalid_reasons = ['Simulation engine not available; statement has not been validated yet.']
            rec.normalized = None
            self._ensure_effective_path(rec)
            return rec

        try:
            result = engine.validate_prospective_statement(rec.statement_text)
        except Exception:  # pragma: no cover - defensive, engine logs details
            logger.warning(
                'ProspectiveStatementsService: error validating prospective statement for record %s',
                record_id,
                exc_info=True,
            )
            rec.parsed = False
            rec.valid = False
            rec.invalid_reasons = [
                'Exception while validating statement; see logs for details.',
            ]
            rec.normalized = None
            return rec

        parsed_flag = bool(result.get('parsed'))
        valid_flag = bool(result.get('valid'))
        reasons = list(result.get('invalid_reasons') or [])

        # Persist engine diagnostics as-is, but deliberately keep
        # ``rec.valid`` False when a parse error occurred so that invalid
        # prospective statements can be surfaced in the Policies tab via
        # its "Invalid Only" filter. A non-empty ``invalid_reasons``
        # list always means the statement is considered invalid, even
        # when ``parsed`` is False.
        rec.parsed = parsed_flag
        rec.invalid_reasons = reasons
        rec.valid = valid_flag and not reasons
        normalized = result.get('normalized')
        if isinstance(normalized, dict):
            rec.normalized = normalized
        else:
            rec.normalized = None

        self._ensure_effective_path(rec)

        logger.debug(
            'ProspectiveStatementsService: validated record %s (parsed=%s, valid=%s)',
            record_id,
            rec.parsed,
            rec.valid,
        )
        return rec

    def persist_and_push_to_engine(self) -> None:
        """Persist current records to settings and push them into the engine.

        This method performs two related operations:

        * Serializes the internal records to the *simple* list format
          expected by :meth:`PolicySimulationEngine.set_prospective_statements`.
        * Writes the same list to settings under the
          ``simulation_prospective_statements_by_tenancy`` key for the
          active tenancy, and attempts to save the settings file.
        """

        # Build the simple list representation expected by the engine,
        # but also allow persisting parsed/normalized details when
        # available so that other components (e.g. Policies tab) can
        # treat prospective statements more like regular statements.
        simple_list: list[dict[str, Any]] = []
        for rec in self._records.values():
            text = (rec.statement_text or '').strip()
            if not text:
                # Skip completely empty rows; they are effectively
                # placeholders in the UI.
                continue
            entry: dict[str, Any] = {
                'compartment_path': rec.compartment_path or 'ROOT',
                'description': rec.description or '',
                'statement_text': text,
            }

            if rec.effective_path:
                entry['effective_path'] = rec.effective_path

            # Persist parsed/valid/normalized details when present so
            # that downstream consumers (such as the Policies tab)
            # can reconstruct a RegularPolicyStatement-like view
            # without having to re-validate immediately.
            entry['parsed'] = bool(rec.parsed)
            entry['valid'] = bool(rec.valid)
            if rec.invalid_reasons:
                entry['invalid_reasons'] = list(rec.invalid_reasons)
            if isinstance(rec.normalized, dict):
                entry['normalized'] = rec.normalized

            simple_list.append(entry)

        logger.info(
            'ProspectiveStatementsService: persisting %d prospective statements for tenancy %s',
            len(simple_list),
            self._tenancy_ocid,
        )

        # Push into the simulation engine so future simulations see the
        # updated set. The engine owns normalization and internal ids.
        engine = self._engine
        if engine is not None and hasattr(engine, 'set_prospective_statements'):
            try:
                engine.set_prospective_statements(simple_list)
            except Exception:  # pragma: no cover - defensive
                logger.warning(
                    'ProspectiveStatementsService: engine.set_prospective_statements failed',
                    exc_info=True,
                )

        # Persist to settings using the same structure described in
        # CONTEXT_simulation_engine.md (section 10).
        all_sim_settings = self._settings.get(SETTINGS_KEY_PROSPECTIVE_BY_TENANCY, {}) or {}
        all_sim_settings[self._tenancy_ocid] = simple_list
        self._settings[SETTINGS_KEY_PROSPECTIVE_BY_TENANCY] = all_sim_settings

        try:
            from oci_policy_analysis.common import config as _cfg

            _cfg.save_settings(self._settings)
        except Exception:  # pragma: no cover - non-fatal persistence
            logger.warning(
                'ProspectiveStatementsService: unable to persist settings; in-memory state and engine are updated',
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_from_settings(self) -> None:
        """Hydrate the in-memory records from the shared settings dict.

        This reads the per-tenancy list under
        ``simulation_prospective_statements_by_tenancy`` and creates a
        corresponding :class:`ProspectiveStatementRecord` for each entry.

        No validation is performed automatically; callers can opt-in by
        iterating :meth:`list_all` and invoking
        :meth:`validate_and_update_text` per record if desired.
        """

        raw_all = self._settings.get(SETTINGS_KEY_PROSPECTIVE_BY_TENANCY, {}) or {}
        raw_list = raw_all.get(self._tenancy_ocid) or []

        logger.info(
            'ProspectiveStatementsService: loading %d prospective statements from settings for tenancy %s',
            len(raw_list),
            self._tenancy_ocid,
        )

        self._records.clear()
        for entry in raw_list:
            # We intentionally ignore any unknown keys so that future
            # extensions of the stored dict shape do not break older
            # service versions. Known keys such as parsed/valid/
            # invalid_reasons/normalized are applied after creation.
            rec = self.create(
                compartment_path=entry.get('compartment_path') or 'ROOT',
                description=entry.get('description') or '',
                statement_text=entry.get('statement_text') or '',
            )
            # Restore parsed/valid/normalized metadata when present so
            # that callers (e.g. Policies tab) can use the record
            # without immediately forcing re-validation.
            if 'parsed' in entry:
                rec.parsed = bool(entry.get('parsed'))
            if 'valid' in entry:
                rec.valid = bool(entry.get('valid'))
            invalid = entry.get('invalid_reasons')
            if isinstance(invalid, list):
                rec.invalid_reasons = [str(x) for x in invalid]
            norm = entry.get('normalized')
            if isinstance(norm, dict):
                rec.normalized = norm
            eff_path = entry.get('effective_path')
            if isinstance(eff_path, str) and eff_path.strip():
                rec.effective_path = eff_path.strip()
            else:
                self._ensure_effective_path(rec)

    # ------------------------------------------------------------------
    # Effective path helpers
    # ------------------------------------------------------------------

    def _get_intelligence_engine(self) -> PolicyIntelligenceEngine | None:
        if self._intelligence_engine_cache is not None:
            return self._intelligence_engine_cache

        engine = self._engine
        policy_repo = getattr(engine, 'policy_repo', None)
        if policy_repo is None:
            return None

        try:
            self._intelligence_engine_cache = PolicyIntelligenceEngine(policy_repo)
        except Exception:  # pragma: no cover - defensive cache creation
            logger.info(
                'ProspectiveStatementsService: unable to initialize PolicyIntelligenceEngine for effective path calculation',
                exc_info=True,
            )
            self._intelligence_engine_cache = None
        return self._intelligence_engine_cache

    def _ensure_effective_path(self, record: ProspectiveStatementRecord) -> None:  # noqa: C901
        """Populate record.effective_path using normalized data and hierarchy."""

        record.effective_path = None
        normalized = record.normalized if isinstance(record.normalized, dict) else {}

        existing = normalized.get('effective_path') if normalized else None
        if isinstance(existing, str) and existing.strip():
            record.effective_path = self._format_effective_path(existing, record.compartment_path)
            if isinstance(record.normalized, dict):
                record.normalized['effective_path'] = record.effective_path
            return

        intelligence_engine = self._get_intelligence_engine()
        if intelligence_engine is None:
            record.effective_path = self._format_effective_path(None, record.compartment_path)
            if isinstance(record.normalized, dict):
                record.normalized.setdefault('effective_path', record.effective_path)
            return

        stmt_for_calc: dict[str, Any] = {}
        if isinstance(normalized, dict):
            stmt_for_calc.update(normalized)

        stmt_for_calc.setdefault('compartment_path', record.compartment_path or 'ROOT')
        if not stmt_for_calc.get('location_type'):
            # Default to compartment-based location matching the stored path
            stmt_for_calc['location_type'] = 'compartment'
        if not stmt_for_calc.get('location'):
            stmt_for_calc['location'] = record.compartment_path or 'ROOT'

        try:
            intelligence_engine.calculate_effective_compartment_for_statement(stmt_for_calc)
        except Exception:  # pragma: no cover - defensive path calculation
            logger.info(
                'ProspectiveStatementsService: failed to calculate effective_path for record %s',
                record.id,
                exc_info=True,
            )
            record.effective_path = self._format_effective_path(None, record.compartment_path)
            if isinstance(record.normalized, dict):
                record.normalized.setdefault('effective_path', record.effective_path)
            return

        eff_path = stmt_for_calc.get('effective_path')
        if isinstance(eff_path, str) and eff_path.strip():
            record.effective_path = self._format_effective_path(eff_path, record.compartment_path)
            if isinstance(record.normalized, dict):
                record.normalized['effective_path'] = record.effective_path
        else:
            record.effective_path = self._format_effective_path(None, record.compartment_path)
            if isinstance(record.normalized, dict):
                record.normalized.setdefault('effective_path', record.effective_path)

    def _format_effective_path(self, path: str | None, compartment_path: str | None) -> str:
        candidate = (path or '').strip()
        fallback = (compartment_path or 'ROOT').strip()

        if not candidate:
            candidate = fallback

        candidate = candidate.replace('\\', '/').strip()
        if candidate.startswith('/'):
            candidate = candidate[1:]

        segments = [seg for seg in (candidate.split('/') if candidate else []) if seg]
        if not segments:
            segments = ['root']
        if segments[0].lower() != 'root':
            segments.insert(0, 'root')

        # Preserve original casing except for enforcing a ROOT prefix and removing duplicate slashes.
        normalized_segments = [segments[0]] + list(segments[1:])
        normalized_segments[0] = 'ROOT'
        return '/'.join(normalized_segments)
