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
from oci_policy_analysis.logic.policy_helpers import calculate_principal_key
from oci_policy_analysis.logic.policy_intelligence import PolicyIntelligenceEngine
from oci_policy_analysis.logic.policy_statement_normalizer import PolicyStatementNormalizer

logger = get_logger(component='prospective_statements_service')


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

    def __init__(self, cache_manager: Any, policy_repo: Any, tenancy_ocid: str):
        if not tenancy_ocid:
            raise ValueError('ProspectiveStatementsService requires a non-empty tenancy_ocid')

        self._cache = cache_manager
        self._policy_repo = policy_repo
        self._tenancy_ocid = str(tenancy_ocid)
        # Internal mapping from record id -> ProspectiveStatementRecord
        self._records: dict[str, ProspectiveStatementRecord] = {}
        self._intelligence_engine_cache: PolicyIntelligenceEngine | None = None
        self._statement_normalizer = PolicyStatementNormalizer()

        logger.info('ProspectiveStatementsService: initializing for tenancy %s', self._tenancy_ocid)
        self._load_from_cache()

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

        try:
            norm = self._statement_normalizer.normalize(rec.statement_text, 'regular', {})
            result = {
                'parsed': bool(norm.get('parsed', False)),
                'valid': bool(norm.get('valid', bool(norm.get('parsed', False)))),
                'invalid_reasons': list(norm.get('invalid_reasons') or []),
                'normalized': norm if bool(norm.get('parsed', False)) else {},
            }
        except Exception:  # pragma: no cover - defensive
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

        self._ensure_principal_keys(rec)
        self._ensure_effective_path(rec)

        logger.debug(
            'ProspectiveStatementsService: validated record %s (parsed=%s, valid=%s)',
            record_id,
            rec.parsed,
            rec.valid,
        )
        return rec

    def persist_and_push_to_engine(self) -> None:
        """Persist current records to standalone prospects storage.

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

        try:
            self._cache.save_prospects(self._tenancy_ocid, simple_list)
        except Exception:  # pragma: no cover - non-fatal persistence
            logger.warning(
                'ProspectiveStatementsService: unable to persist prospects cache; in-memory state is updated',
                exc_info=True,
            )

    def to_simple_list(self) -> list[dict[str, Any]]:
        """Return service records in simple list format for simulation-engine consumption."""
        items: list[dict[str, Any]] = []
        for rec in self._records.values():
            text = (rec.statement_text or '').strip()
            if not text:
                continue
            row: dict[str, Any] = {
                'compartment_path': rec.compartment_path or 'ROOT',
                'description': rec.description or '',
                'statement_text': text,
                'parsed': bool(rec.parsed),
                'valid': bool(rec.valid),
            }
            if rec.invalid_reasons:
                row['invalid_reasons'] = list(rec.invalid_reasons)
            if isinstance(rec.normalized, dict):
                row['normalized'] = rec.normalized
            if rec.effective_path:
                row['effective_path'] = rec.effective_path
            items.append(row)
        return items

    def append_from_simple_dict(self, entry: dict[str, Any]) -> ProspectiveStatementRecord:
        """Append one statement row from UI-style simple dict payload."""
        rec = self.create(
            compartment_path=str(entry.get('compartment_path') or 'ROOT'),
            description=str(entry.get('description') or ''),
            statement_text=str(entry.get('statement_text') or ''),
        )
        if rec.statement_text:
            self.validate_and_update_text(rec.id, rec.statement_text)
        return rec

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_from_cache(self) -> None:
        """Hydrate the in-memory records from standalone per-tenancy prospects cache.

        This reads the per-tenancy list under
        ``simulation_prospective_statements_by_tenancy`` and creates a
        corresponding :class:`ProspectiveStatementRecord` for each entry.

        No validation is performed automatically; callers can opt-in by
        iterating :meth:`list_all` and invoking
        :meth:`validate_and_update_text` per record if desired.
        """

        raw_list = self._cache.load_prospects(self._tenancy_ocid) or []

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
            self._ensure_principal_keys(rec)

    # ------------------------------------------------------------------
    # Effective path helpers
    # ------------------------------------------------------------------

    def _get_intelligence_engine(self) -> PolicyIntelligenceEngine | None:
        if self._intelligence_engine_cache is not None:
            return self._intelligence_engine_cache

        policy_repo = self._policy_repo
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

    def _ensure_principal_keys(self, record: ProspectiveStatementRecord) -> None:
        """Populate principal keys on normalized prospective statements.

        Principals are treated as authoritative when present. We reuse the
        shared helper to ensure the principal_key format matches the rest of
        the application.
        """

        normalized = record.normalized if isinstance(record.normalized, dict) else None
        if not normalized:
            return

        subject_type = (normalized.get('subject_type') or '').strip()
        subjects = normalized.get('subject')
        if not subject_type:
            return

        subj_list = subjects if isinstance(subjects, list) else [subjects]
        principals: list[dict[str, Any]] = []

        if subject_type in ('any-user', 'any-group', 'service'):
            for subj in subj_list:
                name = str(subj or subject_type).strip()
                if not name:
                    continue
                key = calculate_principal_key(subject_type, None, name)
                principals.append(
                    {
                        'principal_type': subject_type,
                        'principal_key': key,
                        'display_name': name,
                        'name': name,
                    }
                )
        elif subject_type in ('group-id', 'dynamic-group-id'):
            for subj in subj_list:
                ocid = str(subj or '').strip()
                if not ocid:
                    continue
                key = f'{subject_type}:{ocid}'
                principals.append(
                    {
                        'principal_type': subject_type,
                        'principal_key': key,
                        'ocid': ocid,
                        'display_name': ocid,
                        'name': ocid,
                    }
                )
        else:
            for subj in subj_list:
                if isinstance(subj, (tuple | list)) and len(subj) == 2:
                    domain, name = subj
                elif isinstance(subj, str):
                    domain, name = None, subj
                else:
                    continue
                name_str = str(name or '').strip()
                if not name_str:
                    continue
                domain_val = str(domain).strip() if domain not in (None, '') else None
                key = calculate_principal_key(subject_type, domain_val, name_str)
                display = f'{domain_val}/{name_str}' if domain_val else name_str
                principals.append(
                    {
                        'principal_type': subject_type,
                        'principal_key': key,
                        'domain_name': domain_val,
                        'display_name': display,
                        'name': name_str,
                    }
                )

        if principals:
            normalized['principals'] = principals
            if len(principals) == 1:
                normalized['principal_key'] = principals[0]['principal_key']
