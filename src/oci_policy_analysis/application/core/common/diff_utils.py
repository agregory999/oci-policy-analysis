##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# diff_utils.py - canonical comparison helpers for OCI diffing
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

"""
Canonicalization function for reference data diffs.

- Used by both Tkinter HistoricalTab and MCP fastmcp_server.
- Takes a nested object graph (dict/list) and returns
  a canonical copy containing only fields relevant for comparison,
  omitting runtime-unique IDs, timestamps, order, and unrelated data.

If this logic changes, update all importers to use this function.
"""

from typing import Any


def canonical_filter(obj: Any) -> Any:
    """
    Reduce large OCI reference structures to only the relevant
    fields before diffing. Keeps only semantically meaningful
    keys to avoid noise and performance hits.
    """
    if isinstance(obj, list):
        return [canonical_filter(x) for x in obj]
    if isinstance(obj, dict):
        # Policy-like objects
        if 'policy_name' in obj or 'statement_text' in obj:
            return {
                k: obj.get(k)
                for k in (
                    'policy_name',
                    'statement_text',
                    'compartment_name',
                    'valid',
                    'invalid',
                    'invalid_reasons',
                )
                if k in obj
            }
        # Identity (user/group/dynamic_group)
        if any(k in obj for k in ('user_name', 'group_name', 'dynamic_group_name')):
            return {
                k: obj.get(k)
                for k in ('domain_name', 'user_name', 'group_name', 'dynamic_group_name', 'groups', 'matching_rule')
                if k in obj
            }
        # Compartments
        if 'hierarchy_path' in obj:
            return {k: obj.get(k) for k in ('id', 'name', 'hierarchy_path', 'parent_id') if k in obj}
        # Generic dict — recurse
        return {k: canonical_filter(v) for k, v in obj.items()}
    # Primitives
    return obj
