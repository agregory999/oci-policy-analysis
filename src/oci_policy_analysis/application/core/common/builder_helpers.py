"""Shared builder helper functions independent of Tk UI package."""

from __future__ import annotations


def build_tag_variable_and_snippet(
    access: str,
    namespace: str,
    key: str,
    operator: str,
    value: str,
) -> tuple[str, str]:
    access = (access or '').strip()
    namespace = (namespace or '').strip()
    key = (key or '').strip()
    op = (operator or '=').strip() or '='
    val = (value or '').strip()

    if not (access and namespace and key):
        return '', ''

    var_name = f'{access}.tag.{namespace}.{key}'
    if op.upper() in {'IN', 'NOT IN'}:
        raw_parts = [p.strip() for p in val.split(',') if p.strip()] if val else []
        values = [p if (len(p) >= 2 and p[0] == '/' and p[-1] == '/') else f"'{p}'" for p in raw_parts]
        list_part = f"({','.join(values)})" if values else '()'
        return var_name, f'all {{ {var_name} {op} {list_part} }}'

    value_part = f"'{val}'" if val else "''"
    return var_name, f'all {{ {var_name} {op} {value_part} }}'


def build_subject_phrase(
    principal_key: str,
    principal_details: dict[str, tuple[str, str | None, str]] | None = None,
) -> str:
    principal_key = (principal_key or '').strip()
    if not principal_key:
        return '<principal>'

    details = principal_details.get(principal_key) if principal_details else None
    if details is not None:
        ptype, domain, name = details
        if ptype == 'service':
            return f'service {name}'
        if ptype in {'group', 'dynamic-group', 'user'}:
            return f"{ptype} '{domain}'/'{name}'" if domain else f"{ptype} '{name}'"
        if ptype == 'group-id':
            return f'group id {name}'
        if ptype == 'dynamic-group-id':
            return f'dynamic-group id {name}'
        return name or principal_key

    return principal_key


def build_location_clause(location_path: str, effective_path: str) -> tuple[str, list[str], list[str]]:
    def _split(path: str) -> list[str]:
        parts = [p for p in (path or '').split('/') if p]
        return parts or ['root']

    loc_parts = _split(location_path or 'root')
    eff_parts = _split(effective_path or location_path or 'root')

    if loc_parts == ['root'] and eff_parts == ['root']:
        return ' in tenancy', loc_parts, eff_parts

    if len(eff_parts) > len(loc_parts) and eff_parts[: len(loc_parts)] == loc_parts:
        remaining = eff_parts[len(loc_parts) :]
        if len(remaining) == 1:
            return f' in compartment {remaining[0]}', loc_parts, eff_parts
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
    eff = (effect or 'Allow').strip().title() or 'Allow'
    subj = subject_phrase or '<principal>'
    v = (verb or 'use').strip() or 'use'
    res = (resource or '<resource>').strip() or '<resource>'
    loc = location_clause or ''
    where = (where_snippet or '').strip()

    base = f'{eff} {subj} to {v} {res}{loc}'
    return f'{base} where {where}' if where else base
