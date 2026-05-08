##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# policy_helpers.py
#
# Shared helper utilities for policy parsing/normalization that can be
# consumed by both data_repo and policy_intelligence layers.
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

from __future__ import annotations

from typing import Any


def calculate_principal_key(subject_type: str, domain: str | None, name: str) -> str:
    """Return the canonical *principal key* string for a subject triple.

    Canonical format is::

        "{subject_type}:{domain}/{name}"

    with the following normalization rules:

    * ``subject_type`` is used as provided (callers typically lowercase).
    * For **user/group/dynamic-group** subjects, if ``domain`` is falsy or
      equal to ``"default"`` (any casing), the domain component is normalized
      to the literal string ``"Default"``.
    * For **any-user/any-group/service** subjects, the domain component is
      always ``"None"`` in the key. The ``name`` piece should carry the
      semantic value.
    """

    stype = (subject_type or '').strip()
    name_str = str(name).strip()
    domain_str: str | None

    if stype in {'any-user', 'any-group', 'service'}:
        domain_str = 'None'
    elif stype in {'user', 'group', 'dynamic-group'}:
        if domain is None:
            domain_str = 'Default'
        else:
            d = str(domain).strip()
            domain_str = 'Default' if d.lower() == 'default' or not d else d
    else:
        domain_str = str(domain) if domain is not None else 'None'

    return f'{stype}:{domain_str}/{name_str}'


def resolve_effective_path(
    *,
    location_type: str | None,
    location: str | None,
    compartment_ocid: str | None,
    tenancy_ocid: str | None,
    policy_path: str | None,
    compartments_by_id: dict[str, dict[str, Any]] | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """Resolve effective path + compartment ocid for a policy statement.

    Returns ``(effective_path, effective_compartment_ocid, parsing_notes)``.
    Consumers can still set these on the statement and append notes.
    """

    notes: list[str] = []

    def _name_path_from_ocid(ocid: str | None) -> str | None:
        if not ocid or not compartments_by_id:
            return None
        comp = compartments_by_id.get(ocid)
        return comp.get('path') if comp else None

    def _comp_name_from_ocid(ocid: str | None) -> str | None:
        if not ocid or not compartments_by_id:
            return None
        comp = compartments_by_id.get(ocid)
        return comp.get('name') if comp else None

    loc_type = (location_type or '').lower()

    if loc_type == 'tenancy':
        effective_compartment_ocid = tenancy_ocid
        eff_path = _name_path_from_ocid(tenancy_ocid)
        return (eff_path.lower() if isinstance(eff_path, str) else eff_path, effective_compartment_ocid, notes)

    if loc_type == 'compartment id':
        effective_compartment_ocid = location
        eff_path = _name_path_from_ocid(location)
        if eff_path:
            eff_path = eff_path.lower()
        notes.append('Compartment ID used for location')
        return (eff_path, effective_compartment_ocid, notes)

    # Compartment name (with or without path) resolution
    parts = [p.strip() for p in (location or '').split(':') if p.strip()]
    eff_path = policy_path
    comp_name = _comp_name_from_ocid(compartment_ocid)

    if parts and comp_name and parts[0].casefold() == comp_name.casefold():
        notes.append('Deleted compartment from effective location')
        del parts[0]

    for part in parts:
        if eff_path is None:
            eff_path = ''
        eff_path += f'/{part}'

    if eff_path:
        eff_path = eff_path.lower()

    effective_compartment_ocid = None
    if compartments_by_id:
        # We only have path->id map at higher layer; caller can resolve if desired.
        pass

    return eff_path, effective_compartment_ocid, notes
