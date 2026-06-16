##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# formatters.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################
"""Presentation-layer formatting helpers."""

import json
from typing import Any

from oci_policy_analysis.application.core.models.models_iam import DynamicGroup, Group, User
from oci_policy_analysis.application.core.models.models_policy import DefineStatement, RegularPolicyStatement
from oci_policy_analysis.application.core.parser.condition_structure import format_condition_structure_summary


def format_compartment_policy_name(
    compartment_path: str | None,
    policy_name: str | None,
    *,
    separator: str = ' :: ',
    empty: str = '-',
) -> str:
    """Format a reusable "compartment path + policy name" display label."""
    comp = str(compartment_path or '').strip()
    name = str(policy_name or '').strip()
    if comp and name:
        return f'{comp}{separator}{name}'
    return name or comp or empty


def for_display_policy(statement: RegularPolicyStatement) -> dict:
    """Return a dictionary suitable for display purposes for policy statements."""
    principals_display = ''
    principals = statement.get('principals')
    principal_keys = statement.get('principal_keys')
    condition_structure = statement.get('where_clause_structure') or statement.get('where_clause') or {}
    condition_structure_summary = str(
        statement.get('conditions_parsed_structure') or format_condition_structure_summary(condition_structure)
    )
    condition_elements = _format_condition_atoms(condition_structure)
    condition_raw = statement.get('conditions', '') if 'conditions' in statement else ''
    confidence = statement.get('confidence') or statement.get('match_confidence') or ''
    match_confidence = statement.get('match_confidence') or statement.get('confidence') or ''
    match_confidence_reason = statement.get('match_confidence_reason') or ''
    principal_evidence = statement.get('principal_evidence') or []
    residual_conditions = statement.get('residual_conditions') or []
    principal_evidence_display = _format_condition_atoms({'atoms': principal_evidence})
    residual_conditions_display = _format_condition_atoms({'atoms': residual_conditions})
    if isinstance(principals, list):
        principals_display = ', '.join(
            [(p.get('display_name') or p.get('principal_key') or '') for p in principals if isinstance(p, dict)]
        )
    elif isinstance(principal_keys, list):
        principals_display = ', '.join(str(k) for k in principal_keys if k)

    row = {
        'Action': statement.get('action', 'allow'),
        'Policy Name': statement['policy_name'],  # type: ignore
        'Policy OCID': statement['policy_ocid'],  # type: ignore
        'Internal ID': statement['internal_id'],  # type: ignore
        'Compartment OCID': statement['compartment_ocid'],  # type: ignore
        'Policy Compartment': statement['compartment_path'],  # type: ignore
        'Statement Text': statement['statement_text'],  # type: ignore
        'Valid': statement['valid'],  # type: ignore
        'Invalid Reasons': ', '.join(statement['invalid_reasons'])
        if 'invalid_reasons' in statement and isinstance(statement['invalid_reasons'], list)
        else '',
        'Subject Type': statement['subject_type'] if 'subject_type' in statement else '',
        'Subject': statement['subject'] if 'subject' in statement else '',
        'Principals': principals_display,
        'Principal Keys': ', '.join(str(k) for k in principal_keys) if isinstance(principal_keys, list) else '',
        '_Principals Raw': principals,
        'Verb': statement['verb'] if 'verb' in statement else '',
        'Resource': statement['resource'] if 'resource' in statement else '',
        'Permission': statement['permission'] if 'permission' in statement else '',
        'Location Type': statement['location_type'] if 'location_type' in statement else '',
        'Location': statement['location'] if 'location' in statement else '',
        'Effective Path': statement['effective_path'] if 'effective_path' in statement else '',
        'Conditions': condition_raw,
        'Conditions (where clause)': condition_raw,
        'Conditions (parsed structure)': condition_structure_summary,
        'Conditions (elements)': condition_elements,
        'Where Structure': condition_structure_summary,
        'Comments': statement['comments'] if 'comments' in statement else '',
        'Parsing Notes': '; '.join(statement['parsing_notes']) if 'parsing_notes' in statement else '',
        'Creation Time': statement['creation_time'] if 'creation_time' in statement else '',
        'Parsed': statement['parsed'] if 'parsed' in statement else '',
        'Confidence': confidence,
        'Match Confidence': match_confidence,
        'Match Confidence Reason': match_confidence_reason,
        'Principal Evidence': principal_evidence_display,
        'Residual Conditions': residual_conditions_display,
    }

    # Include snake_case aliases so web views can reliably access keys like
    # policy_ocid/effective_path without title/acronym mismatches.
    row.update(
        {
            'action': statement.get('action', 'allow'),
            'policy_name': statement.get('policy_name', ''),
            'policy_ocid': statement.get('policy_ocid', ''),
            'internal_id': statement.get('internal_id', ''),
            'compartment_ocid': statement.get('compartment_ocid', ''),
            'policy_compartment': statement.get('compartment_path', ''),
            'statement_text': statement.get('statement_text', ''),
            'valid': statement.get('valid', ''),
            'invalid_reasons': statement.get('invalid_reasons', []),
            'subject_type': statement.get('subject_type', ''),
            'subject': statement.get('subject', ''),
            # Keep Principals display string for tabular views, but expose raw list for inspectors.
            'principals': principals if isinstance(principals, list) else [],
            'principal_keys': principal_keys if isinstance(principal_keys, list) else [],
            'verb': statement.get('verb', ''),
            'resource': statement.get('resource', ''),
            'permission': statement.get('permission', ''),
            'location_type': statement.get('location_type', ''),
            'location': statement.get('location', ''),
            'effective_path': statement.get('effective_path', ''),
            'conditions': condition_raw,
            'conditions_where_clause': statement.get('conditions_where_clause', condition_raw),
            'conditions_parsed_structure': condition_structure_summary,
            'conditions_elements': condition_elements,
            'condition_atoms': condition_structure.get('atoms', []) if isinstance(condition_structure, dict) else [],
            'where_clause': condition_structure,
            'where_clause_structure': condition_structure,
            'where_structure': condition_structure_summary,
            'comments': statement.get('comments', ''),
            'parsing_notes': statement.get('parsing_notes', []),
            'creation_time': statement.get('creation_time', ''),
            'parsed': statement.get('parsed', ''),
            'confidence': confidence,
            'match_confidence': match_confidence,
            'match_confidence_reason': match_confidence_reason,
            'principal_evidence': principal_evidence if isinstance(principal_evidence, list) else [],
            'residual_conditions': residual_conditions if isinstance(residual_conditions, list) else [],
        }
    )

    return row


def for_display_tag_based_policy_row(statement: RegularPolicyStatement) -> dict:
    """Return a compact, tag-focused display dict for a regular statement."""

    return {
        'Policy Name': statement.get('policy_name', ''),
        'Effective Path': statement.get('effective_path') or statement.get('compartment_path', ''),
        'Statement Text': statement.get('statement_text', ''),
        'Subject Type': statement.get('subject_type', ''),
        'Subject': statement.get('subject', ''),
        'Verb': statement.get('verb', ''),
        'Resource': statement.get('resource', ''),
        'Conditions': statement.get('conditions', ''),
    }


def for_display_user(u: User) -> dict:
    """Return a dictionary suitable for display purposes for users."""
    return {
        'Domain Name': u['domain_name'] if u['domain_name'] else 'Default',  # type: ignore
        'Username': u['user_name'],
        'User ID': u.get('user_id', 'N/A'),
        'User OCID': u.get('user_ocid', 'N/A'),
        'Primary Email': u.get('email', 'N/A'),
        'Display Name': u.get('display_name', 'N/A'),
        'User Groups': ', '.join(u.get('groups', [])) if u.get('groups') else 'N/A',  # type: ignore
    }  # type: ignore


def for_display_group(g: Group) -> dict:
    """Return a dictionary suitable for display purposes for groups."""
    return {
        'Domain Name': g['domain_name'] if g['domain_name'] else 'Default',  # type: ignore
        'Group Name': g['group_name'],
        'Group ID': g.get('group_id', 'N/A'),
        'Group OCID': g.get('group_ocid', 'N/A'),
        'Description': g.get('description', 'N/A'),
    }  # type: ignore


def for_display_dynamic_group(dg: DynamicGroup) -> dict:
    """Return a dictionary suitable for display purposes for dynamic groups."""
    rule_structure = dg.get('matching_rule_structure') or {}
    rule_structure_summary = str(
        dg.get('matching_rule_parsed_structure') or format_condition_structure_summary(rule_structure)
    )
    rule_elements = _format_condition_atoms(rule_structure)
    return {
        'Domain': dg['domain_name'] if dg['domain_name'] else 'Default',  # type: ignore
        'Domain OCID': dg.get('domain_ocid', 'N/A'),
        'DG Name': dg['dynamic_group_name'],
        'DG ID': dg.get('dynamic_group_id', 'N/A'),
        'DG OCID': dg.get('dynamic_group_ocid', 'N/A'),
        'Description': dg.get('description', 'N/A'),
        'Matching Rule': dg.get('matching_rule', 'N/A'),
        'Matching Rule (parsed structure)': rule_structure_summary,
        'Matching Rule (elements)': rule_elements,
        'Rule Structure': rule_structure_summary,
        'In Use': dg.get('in_use', False),
        'Creation Time': dg.get('creation_time', 'N/A'),
        'Created By': dg.get('created_by_name', 'N/A'),
        'Created By OCID': dg.get('created_by_ocid', 'N/A'),
        'matching_rule_parsed_structure': rule_structure_summary,
        'matching_rule_elements': rule_elements,
        'matching_rule_structure': dg.get('matching_rule_structure') or {},
    }  # type: ignore


def _format_condition_atoms(structure: object) -> str:
    """Return compact display lines for parsed condition/rule atoms."""
    if not isinstance(structure, dict):
        return ''
    atoms = structure.get('atoms')
    if not isinstance(atoms, list):
        return ''
    lines: list[str] = []
    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        atom_id = str(atom.get('id') or '').strip()
        left = str(atom.get('left') or '').strip()
        operator = str(atom.get('operator') or '').strip()
        right = str(atom.get('right') or '').strip()
        evidence_kind = str(atom.get('evidence_kind') or '').strip()
        expr = ' '.join(part for part in [left, operator, right] if part)
        prefix = f'{atom_id}: ' if atom_id else ''
        suffix = f' [{evidence_kind}]' if evidence_kind else ''
        if expr:
            lines.append(f'{prefix}{expr}{suffix}')
    return '\n'.join(lines)


def for_display_define(define: DefineStatement) -> dict:
    """Return a dictionary suitable for display purposes for defines."""
    return {
        'Policy Name': define.get('policy_name', ''),
        'Defined Type': define.get('defined_type', ''),
        'Defined Name': define.get('defined_name', ''),
        'OCID Alias': define.get('ocid_alias', ''),
    }


def for_display_admit(statement) -> dict:
    """Display-friendly dict for parsed AdmitStatement, mapped to UI columns."""
    permissions_list_display = ''
    if 'admit_permissions' in statement:
        if isinstance(statement['admit_permissions'], list) and len(statement['admit_permissions']) > 0:
            permissions_list_display = '{' + ', '.join(statement['admit_permissions']) + '}'
        elif isinstance(statement['admit_permissions'], str):
            permissions_list_display = '{' + statement['admit_permissions'] + '}'

    return {
        'Policy Name': statement.get('policy_name', ''),
        'Policy Compartment': statement.get('compartment_path', ''),
        'Statement Text': statement.get('statement_text', ''),
        'Creation Time': statement.get('creation_time', ''),
        'Parsed': statement.get('parsed', False),
        'Action Type': statement.get('action_type', ''),
        'Admitted Principal Type': statement.get('admitted_principal_type', ''),
        'Admitted Principals': ', '.join(statement.get('admitted_principal', []))
        if isinstance(statement.get('admitted_principal', []), list)
        else statement.get('admitted_principal', ''),
        'Admitted Tenancy': statement.get('admitted_tenancy', ''),
        'Admitted Action (or Permission)': f"{statement.get('admit_action', '')} {statement.get('admit_resource', '')}{permissions_list_display}",
        'Location Type': statement.get('admit_location_type', ''),
        'Location': statement.get('admit_location', ''),
        'Where Clause': statement.get('where_clause', ''),
        'Comments': statement.get('comment', ''),
    }


def for_display_endorse(statement) -> dict:
    """Display-friendly dict for parsed EndorseStatement, mapped to UI columns."""
    permissions_list_display = ''
    if 'endorse_permissions' in statement:
        if isinstance(statement['endorse_permissions'], list) and len(statement['endorse_permissions']) > 0:
            permissions_list_display = '{' + ', '.join(statement['endorse_permissions']) + '}'
        elif isinstance(statement['endorse_permissions'], str):
            permissions_list_display = '{' + statement['endorse_permissions'] + '}'

    return {
        'Policy Name': statement.get('policy_name', ''),
        'Policy OCID': statement.get('policy_ocid', ''),
        'Statement Text': statement.get('statement_text', ''),
        'Creation Time': statement.get('creation_time', ''),
        'Parsed': statement.get('parsed', False),
        'Action Type': statement.get('action_type', ''),
        'Endorsed Principal Type': statement.get('endorsed_principal_type', ''),
        'Endorsed Principals': ', '.join(statement.get('endorsed_principal', []))
        if isinstance(statement.get('endorsed_principal', []), list)
        else statement.get('endorsed_principal', ''),
        'Endorsed Action (or Permission)': f"{statement.get('endorse_action', '')} {statement.get('endorse_resource', '')}{permissions_list_display}",
        'Endorsed Tenancy Name': statement.get('endorse_tenancy', ''),
        'Where Clause': statement.get('where_clause', ''),
        'Comments': statement.get('comment', ''),
    }


def format_historical_diff_detail(old_value: dict[str, Any] | None, new_value: dict[str, Any] | None) -> list[str]:
    """Return display-friendly lines for historical compare detail payloads."""
    lines: list[str] = []
    if old_value is not None:
        lines.append(f'Old: {json.dumps(old_value, ensure_ascii=False, indent=2)}')
    if new_value is not None:
        lines.append(f'New: {json.dumps(new_value, ensure_ascii=False, indent=2)}')
    return lines


def format_historical_changed_fields(changed_fields: list[dict[str, Any]] | None) -> list[str]:
    """Return compact one-level field diff lines for modified historical items."""
    if not changed_fields:
        return []
    lines: list[str] = []
    for change in changed_fields:
        field = str(change.get('field') or '')
        old = json.dumps(change.get('old'), ensure_ascii=False)
        new = json.dumps(change.get('new'), ensure_ascii=False)
        lines.append(f'{field}: {old} -> {new}')
    return lines
