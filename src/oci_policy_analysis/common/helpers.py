##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# helpers.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################
from oci_policy_analysis.common.models import (
    BasePolicyStatement,
    DefineStatement,
    DynamicGroup,
    Group,
    RegularPolicyStatement,
    User,
)


# Return a display-friendly dict for a policy statement
def for_display_policy(statement: RegularPolicyStatement) -> dict:
    """
    Return a dictionary suitable for display purposes. The underlying dict has many fields, some of which
    may not be present depending on how the statement was parsed. Display dict includes all possible fields with
    display-friendly names.

    Args:
        statement (PolicyStatement): The policy statement (dict) to format.

    Returns:
        dict: A dictionary with keys and values formatted for display.
    """
    return {
        'Action': statement.get('action', 'allow'),
        'Policy Name': statement['policy_name'],  # type: ignore
        'Policy OCID': statement['policy_ocid'],  # type: ignore
        'Internal ID': statement['internal_id'],  # type: ignore
        'Compartment OCID': statement['compartment_ocid'],  # type: ignore
        'Policy Compartment': statement['compartment_path'],  # type: ignore
        'Statement Text': statement['statement_text'],  # type: ignore
        'Valid': statement['valid'],  # type: ignore
        'Invalid Reasons': ', '.join(statement['invalid_reasons'])
        if 'invalid_reasons' in statement and type(statement['invalid_reasons']) is list
        else '',
        'Subject Type': statement['subject_type'] if 'subject_type' in statement else '',
        'Subject': statement['subject'] if 'subject' in statement else '',
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
        'Policy Overlap': '; '.join([str(po) for po in statement['policy_overlap']])
        if 'policy_overlap' in statement
        else '',
    }


# Return a display-friendly dict for a user statement
def for_display_user(u: User) -> dict:
    """
    Return a dictionary suitable for display purposes. The underlying dict has many fields, some of which
    may not be present depending on how the statement was parsed. Display dict includes all possible fields with
    display-friendly names.

    Args:
        u (User): The user (dict) to format.

    Returns:
        dict: A dictionary with keys and values formatted for display.
    """
    return {
        'Domain Name': u['domain_name'] if u['domain_name'] else 'Default',  # type: ignore
        'Username': u['user_name'],
        'User ID': u.get('user_id', 'N/A'),
        'User OCID': u.get('user_ocid', 'N/A'),
        'Primary Email': u.get('email', 'N/A'),
        'Display Name': u.get('display_name', 'N/A'),
        'User Groups': ', '.join(u.get('groups', [])) if u.get('groups') else 'N/A',  # type: ignore
    }  # type: ignore


# Return a display-friendly dict for a group statement
def for_display_group(g: Group) -> dict:
    """
    Return a dictionary suitable for display purposes. The underlying dict has many fields, some of which
    may not be present depending on how the statement was parsed. Display dict includes all possible fields with
    display-friendly names.

    Args:
        g (Group): The group (dict) to format.

    Returns:
        dict: A dictionary with keys and values formatted for display.
    """
    return {
        'Domain Name': g['domain_name'] if g['domain_name'] else 'Default',  # type: ignore
        'Group Name': g['group_name'],
        'Group ID': g.get('group_id', 'N/A'),
        'Group OCID': g.get('group_ocid', 'N/A'),
        'Description': g.get('description', 'N/A'),
    }  # type: ignore


# Return a display-friendly dict for a dynamic group
def for_display_dynamic_group(dg: DynamicGroup) -> dict:
    """
    Return a dictionary suitable for display purposes. The underlying dict has many fields, some of which
    may not be present depending on how the statement was parsed. Display dict includes all possible fields with
    display-friendly names.

    Args:
        dg (DynamicGroup): The dynamic group (dict) to format.

    Returns:
        dict: A dictionary with keys and values formatted for display.
    """
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


# Return a display-friendly dict for a defined alias
def for_display_define(define: DefineStatement) -> dict:
    """
    Return a dictionary suitable for display purposes. The underlying dict has many fields, some of which
    may not be present depending on how the statement was parsed. Display dict includes all possible fields with
    display-friendly names.

    Args:
        define (DefineStatement): The define statement (dict) to format.

    Returns:
        dict: A dictionary with keys and values formatted for display.
    """
    return {
        'Policy Name': define['policy_name'],  # type: ignore
        'Defined Type': define['defined_type'],  # type: ignore
        'Defined Name': define['defined_name'],  # type: ignore
        'OCID Alias': define['ocid_alias'],  # type: ignore
        'Statement Text': define['statement_text'],  # type: ignore
        'Creation Time': define['creation_time'],  # type: ignore
    }


# Return a display-friendly dict for a cross-tenancy policy statement
def for_display_cross_tenancy(statement: BasePolicyStatement) -> dict:
    """
    Return a dictionary suitable for display purposes. The underlying dict has many fields, some of which
    may not be present depending on how the statement was parsed. Display dict includes all possible fields with
    display-friendly names.

    Args:
        statement (PolicyStatement): The cross-tenancy policy statement (dict) to format.

    Returns:
        dict: A dictionary with keys and values formatted for display.
    """
    display_dict = {
        'Policy Name': statement['policy_name'],
        'Policy OCID': statement['policy_ocid'],
        'Policy Compartment': statement['policy_compartment'],
        'Statement Text': statement['statement_text'],
        'Creation Time': statement['creation_time'],
    }
    return display_dict
