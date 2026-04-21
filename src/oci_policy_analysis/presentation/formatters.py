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

from oci_policy_analysis.common.models_iam import DynamicGroup, Group, User
from oci_policy_analysis.common.models_policy import DefineStatement, RegularPolicyStatement


def for_display_policy(statement: RegularPolicyStatement) -> dict:
    """Return a dictionary suitable for display purposes for policy statements."""
    principals_display = ''
    principals = statement.get('principals')
    if isinstance(principals, list):
        principals_display = ', '.join(
            [(p.get('display_name') or p.get('principal_key') or '') for p in principals if isinstance(p, dict)]
        )

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
        '_Principals Raw': principals,
        'Verb': statement['verb'] if 'verb' in statement else '',
        'Resource': statement['resource'] if 'resource' in statement else '',
        'Permission': statement['permission'] if 'permission' in statement else '',
        'Location Type': statement['location_type'] if 'location_type' in statement else '',
        'Location': statement['location'] if 'location' in statement else '',
        'Effective Path': statement['effective_path'] if 'effective_path' in statement else '',
        'Conditions': statement['conditions'] if 'conditions' in statement else '',
        'Comments': statement['comments'] if 'comments' in statement else '',
        'Parsing Notes': '; '.join(statement['parsing_notes']) if 'parsing_notes' in statement else '',
        'Creation Time': statement['creation_time'] if 'creation_time' in statement else '',
        'Parsed': statement['parsed'] if 'parsed' in statement else '',
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
            'verb': statement.get('verb', ''),
            'resource': statement.get('resource', ''),
            'permission': statement.get('permission', ''),
            'location_type': statement.get('location_type', ''),
            'location': statement.get('location', ''),
            'effective_path': statement.get('effective_path', ''),
            'conditions': statement.get('conditions', ''),
            'comments': statement.get('comments', ''),
            'parsing_notes': statement.get('parsing_notes', []),
            'creation_time': statement.get('creation_time', ''),
            'parsed': statement.get('parsed', ''),
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
    return {
        'Domain': dg['domain_name'] if dg['domain_name'] else 'Default',  # type: ignore
        'Domain OCID': dg.get('domain_ocid', 'N/A'),
        'DG Name': dg['dynamic_group_name'],
        'DG ID': dg.get('dynamic_group_id', 'N/A'),
        'DG OCID': dg.get('dynamic_group_ocid', 'N/A'),
        'Description': dg.get('description', 'N/A'),
        'Matching Rule': dg.get('matching_rule', 'N/A'),
        'In Use': dg.get('in_use', False),
        'Creation Time': dg.get('creation_time', 'N/A'),
        'Created By': dg.get('created_by_name', 'N/A'),
        'Created By OCID': dg.get('created_by_ocid', 'N/A'),
    }  # type: ignore


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
    if 'admit_permission_set' in statement:
        if isinstance(statement['admit_permission_set'], list) and len(statement['admit_permission_set']) > 0:
            permissions_list_display = '{' + ', '.join(statement['admit_permission_set']) + '}'
        elif isinstance(statement['admit_permission_set'], str):
            permissions_list_display = '{' + statement['admit_permission_set'] + '}'

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
