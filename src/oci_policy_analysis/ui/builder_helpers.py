##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl/
#
# builder_helpers.py
#
# Shared helper functions for constructing OCI IAM policy statements and
# tag-based where clauses. Extracted from TagBasedAccessTab so that both
# the Tag-based tab and the Prospective editor/builder can reuse the
# same semantics for subject phrases, location clauses, and tag
# condition snippets.
#
# Supports Python 3.12 and above
#
# @author: Cline AI
#
# coding: utf-8
##########################################################################

from __future__ import annotations


def build_tag_variable_and_snippet(
    access: str,
    namespace: str,
    key: str,
    operator: str,
    value: str,
) -> tuple[str, str]:
    """Return (variable_name, condition_snippet) for a tag-based clause.

    Mirrors the logic previously embedded in TagBasedAccessTab's
    builder preview:

    * Variable form: ``"{access}.tag.{namespace}.{key}"``.
    * Scalar comparison: ``all { var op 'value' }``.
    * IN/NOT IN: comma-separated list `value` -> parenthesized, quoted
      list, preserving regex/pattern forms wrapped in ``/..../``.
    """

    access = (access or '').strip()
    namespace = (namespace or '').strip()
    key = (key or '').strip()
    op = (operator or '=').strip() or '='
    val = (value or '').strip()

    if not (access and namespace and key):
        return '', ''

    var_name = f'{access}.tag.{namespace}.{key}'

    snippet = ''
    if op.upper() in {'IN', 'NOT IN'}:
        values: list[str] = []
        if val:
            raw_parts = [p.strip() for p in val.split(',') if p.strip()]
            values = [p if (len(p) >= 2 and p[0] == '/' and p[-1] == '/') else f"'{p}'" for p in raw_parts]
        list_part = f"({','.join(values)})" if values else '()'
        snippet = f'all {{ {var_name} {op} {list_part} }}'
    else:
        value_part = f"'{val}'" if val else "''"
        snippet = f'all {{ {var_name} {op} {value_part} }}'

    return var_name, snippet


def build_subject_phrase(
    principal_key: str,
    principal_details: dict[str, tuple[str, str | None, str]] | None = None,
) -> str:
    """Build a human-readable subject phrase from a Simulation-style principal key.

    ``principal_details`` is optional; when provided, it should map the
    principal_key to a tuple of ``(ptype, domain, name)``. This mirrors
    the internal cache used by TagBasedAccessTab.
    """

    principal_key = (principal_key or '').strip()
    if not principal_key:
        return '<principal>'

    if principal_details:
        details = principal_details.get(principal_key)
    else:
        details = None

    if details is not None:
        ptype, domain, name = details
        if ptype == 'service':
            return f'service {name}'
        if ptype in {'group', 'dynamic-group', 'user'}:
            if domain:
                return f"{ptype} '{domain}'/'{name}'"
            return f"{ptype} '{name}'"
        if ptype == 'group-id':
            return f'group id {name}'
        if ptype == 'dynamic-group-id':
            return f'dynamic-group id {name}'
        return name or principal_key

    # Fallback when no structured details are available.
    return principal_key


def build_location_clause(
    location_path: str,
    effective_path: str,
) -> tuple[str, list[str], list[str]]:
    """Return (location_clause, loc_parts, eff_parts) for a statement.

    This mirrors the path/compartment handling in TagBasedAccessTab but
    refines how we render nested subcompartments so the text matches
    common OCI policy patterns:

    * Both ``root`` -> "in tenancy".
    * When the effective path extends the location path, we look only at
      the **trailing** portion relative to the location and render:

      - If there is **one** additional level, e.g. location ``A`` and
        effective path ``A/B`` -> ``" in compartment B"``.
      - If there are **two or more** additional levels, e.g. location
        ``A`` and effective path ``A/B/C`` -> ``" in compartment B:C"``
        (colon notation for nested subcompartments).
    * When the effective path does not cleanly extend the location
      (different branch or shorter), fall back to using the last segment
      of the effective path: ``" in compartment <last-segment>"``.
    """

    def _split(path: str) -> list[str]:
        parts = [p for p in (path or '').split('/') if p]
        return parts or ['root']

    loc_parts = _split(location_path or 'root')
    eff_parts = _split(effective_path or location_path or 'root')

    if loc_parts == ['root'] and eff_parts == ['root']:
        return ' in tenancy', loc_parts, eff_parts

    if len(eff_parts) > len(loc_parts) and eff_parts[: len(loc_parts)] == loc_parts:
        remaining = eff_parts[len(loc_parts) :]
        # One extra level: "in compartment X" (location A, effective A/B).
        if len(remaining) == 1:
            return f' in compartment {remaining[0]}', loc_parts, eff_parts

        # Two or more extra levels: use colon notation for the tail so
        # that deeply nested paths read like "in compartment B:C" when
        # the location is A and the effective path is A/B/C.
        head = remaining[0]
        tail = ':'.join(remaining[1:])
        return f' in compartment {head}:{tail}', loc_parts, eff_parts

    if eff_parts:
        return f' in compartment {eff_parts[-1]}', loc_parts, eff_parts

    return '', loc_parts, eff_parts


def build_full_statement(
    effect: str,
    subject_phrase: str,
    verb: str,
    resource: str,
    location_clause: str,
    where_snippet: str | None = None,
) -> str:
    """Synthesize a full OCI-style policy statement string.

    Example output::

        Allow group 'Finance' to use buckets in compartment Finance where all { ... }
    """

    eff = (effect or 'Allow').strip().title() or 'Allow'
    subj = subject_phrase or '<principal>'
    v = (verb or 'use').strip() or 'use'
    res = (resource or '<resource>').strip() or '<resource>'
    loc = location_clause or ''
    where = (where_snippet or '').strip()

    base = f'{eff} {subj} to {v} {res}{loc}'
    if where:
        return f'{base} where {where}'
    return base
