##########################################################################
# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# console_tab.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################


"""
policy_statement_normalizer.py

Centralizes post-parsing normalization of OCI IAM policy statements.
- Calls an internal ANTLR parser (PolicyStatementParser) for lexical/syntactical analysis.
- Normalizes parsed output to conform to models: DefineStatement, AdmitStatement, EndorseStatement, RegularPolicyStatement.
- Handles field splitting, comment extraction, tenancy/principal mapping, etc.
- Provides logging for parse/normalization errors and field extraction issues.

Usage:
    from .policy_statement_normalizer import PolicyStatementNormalizer
    stmt = PolicyStatementNormalizer(logger=your_logger).normalize(statement_text, statement_type, base_fields)
"""

import logging
import re

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener
from antlr4.tree.Tree import TerminalNode

from oci_policy_analysis.application.core.common.policy_helpers import calculate_principal_key
from oci_policy_analysis.application.core.models.models import (
    AdmitStatement,
    DefineStatement,
    EndorseStatement,
    RegularPolicyStatement,
)
from oci_policy_analysis.application.core.parser.condition_structure import (
    format_condition_structure_summary,
    parse_condition_structure,
)
from oci_policy_analysis.application.core.parser.generated.policy_parser import PolicyLexer, PolicyParser, PolicyVisitor
from oci_policy_analysis.application.core.parser.policy_subject_parser import parse_policy_subjects
from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='core.parser.policy_statement_normalizer')


class LoggingErrorListener(ErrorListener):
    """Custom ANTLR error listener that logs all syntax errors/warnings via the provided logger."""

    def __init__(self, logger=None, context_text=None):
        super().__init__()
        self.logger = logger or logging.getLogger('antlr')
        self.errors = []
        self.warnings = []
        self.context_text = context_text

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        line_info = f'at line {line}, column {column}'
        context = f' while parsing: {self.context_text!r}' if self.context_text else ''
        full_msg = f'ANTLR syntax error {line_info}{context}: {msg}'
        self.errors.append(full_msg)
        if self.logger:
            self.logger.debug(full_msg)

    def reportAmbiguity(self, recognizer, dfa, startIndex, stopIndex, exact, ambigAlts, configs):
        msg = f'ANTLR ambiguity from {startIndex} to {stopIndex}.'
        self.warnings.append(msg)
        if self.logger:
            self.logger.debug(msg)

    def reportAttemptingFullContext(self, recognizer, dfa, startIndex, stopIndex, conflictingAlts, configs):
        msg = f'ANTLR attempting full context from {startIndex} to {stopIndex}.'
        self.warnings.append(msg)
        if self.logger:
            self.logger.debug(msg)

    def reportContextSensitivity(self, recognizer, dfa, startIndex, stopIndex, prediction, configs):
        msg = f'ANTLR context sensitivity from {startIndex} to {stopIndex}.'
        self.warnings.append(msg)
        if self.logger:
            self.logger.debug(msg)


class _FieldCollectingVisitor(PolicyVisitor):
    def __init__(self, input_text=None):
        super().__init__()
        self._input_text = input_text

    def _get_text(self, ctx_child):
        if ctx_child is None:
            return ''
        if hasattr(ctx_child, 'start') and hasattr(ctx_child, 'stop') and self._input_text:
            start = ctx_child.start.start
            stop = ctx_child.stop.stop
            if isinstance(start, int) and isinstance(stop, int) and stop >= start:
                return self._input_text[start : stop + 1]
        if isinstance(ctx_child, list):
            if len(ctx_child) == 0:
                return ''
            return ctx_child[0].getText()
        return ctx_child.getText()

    def _parse_location_from_scope(self, scope_str):  # noqa: C901
        """Given a scope string, return (location_type, location)"""
        if not scope_str or not isinstance(scope_str, str):
            return ('', '')
        scope = scope_str.strip()
        lower_scope = scope.lower()
        compartment_ocid_pattern = r'ocid1\.compartment\..+'
        tenancy_ocid_pattern = r'ocid1\.tenancy\..+'
        if lower_scope == 'tenancy':
            return ('tenancy', 'tenancy')
        if lower_scope.startswith('compartmentid'):
            match = re.match(
                r'compartmentid(ocid1\.compartment\.[a-zA-Z0-9.\-]+|ocid1\.tenancy\.[a-zA-Z0-9.\-]+)(?:[.:](.*))?$',
                scope,
                re.IGNORECASE,
            )
            if match:
                ocid = match.group(1)
                trail = match.group(2)
                if re.match(tenancy_ocid_pattern, ocid):
                    return ('tenancy', '')
                if re.match(compartment_ocid_pattern, ocid):
                    if trail and ('tenancy' in trail.lower()):
                        return ('tenancy', ocid)
                    elif trail:
                        return ('compartment id', ocid)
                    else:
                        return ('compartment id', ocid)
                else:
                    return ('compartment id', ocid)
            else:
                return ('compartment id', scope)
        compid_match = re.match(r'compartment\s*id\s+(ocid1\.(?:compartment|tenancy)\.[a-zA-Z0-9.\-]+)', lower_scope)
        if compid_match:
            ocid = compid_match.group(1)
            if re.match(tenancy_ocid_pattern, ocid):
                return ('tenancy', '')
            return ('compartment id', ocid)
        if re.match(compartment_ocid_pattern, scope):
            return ('compartment id', scope)
        if re.match(tenancy_ocid_pattern, scope):
            return ('tenancy', scope)
        if 'tenancy' in lower_scope:
            parts = re.split(r'[.:]', scope)
            try:
                idx = [p.lower() for p in parts].index('tenancy')
                value = parts[idx + 1] if idx + 1 < len(parts) else 'tenancy'
                return ('tenancy', value)
            except Exception:
                return ('tenancy', scope)
        if lower_scope.startswith('compartment') and not lower_scope.startswith('compartmentid'):
            match = re.match(r'compartment[.:]?(.*)', scope, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                return ('compartment', name)
            else:
                return ('compartment', scope)
        if '.' in scope or ':' in scope:
            last = re.split(r'[.:]', scope)[-1]
            return ('compartment', last.strip())
        return ('compartment', scope.strip())

    def _get_action_prefix(self, ctx):
        tokens = []
        for i in range(ctx.getChildCount()):
            child = ctx.getChild(i)
            txt = child.getText().lower()
            if txt in ('allow', 'deny', 'admit', 'endorse'):
                tokens.append(txt)
            else:
                break
        return ' '.join(tokens) if tokens else ''

    def visitAllowExpression(self, ctx):  # noqa: C901
        fields = {}
        action = self._get_action_prefix(ctx)
        fields['type'] = 'allow' if action == 'allow' else action
        fields['action'] = action

        # Extract subject_type and raw_subject for use in the central parser
        subject_type = None
        try:
            _first_token = ctx.getChild(0).getText().lower()
            candidate = ctx.getChild(1).getText().lower() if ctx.getChildCount() > 1 else ''
            if candidate in ('group', 'dynamic-group', 'service', 'any-user', 'any-group', 'resource'):
                subject_type = candidate
            else:
                subj_ctx = ctx.subject()
                if subj_ctx:
                    if subj_ctx.groupSubject():
                        subject_type = 'group'
                    elif subj_ctx.dynamicGroupSubject():
                        subject_type = 'dynamic-group'
                    elif subj_ctx.serviceSubject():
                        subject_type = 'service'
                    elif subj_ctx.resourceSubject():
                        subject_type = 'resource'
                    elif subj_ctx.ANYUSER():
                        subject_type = 'any-user'
        except Exception:
            subject_type = ''
        fields['subject_type'] = subject_type or ''
        # Extract only the subject names without the type prefix for group/dynamic-group
        logger.debug(
            f"[WARNING] Extracting raw subject for type '{fields['subject_type']}' from context: {ctx.subject()}"
        )
        ctx_subject = ctx.subject()
        if fields['subject_type'] in ('group', 'dynamic-group') and ctx_subject:
            # Standard extraction
            children = list(ctx_subject.getChildren()) if hasattr(ctx_subject, 'getChildren') else []
            child_texts = [str(c.getText()) for c in children] if children else []
            logger.info(
                f"[DEBUG] group/dynamic-group subject extraction: ctx_subject={ctx_subject}, "
                f"subject_type={fields['subject_type']}, "
                f"len(children)={len(child_texts)}, child_texts={child_texts}"
            )
            if children and len(children) == 1:
                text = str(children[0].getText())
            else:
                # Use ctx_subject's getText output as fallback
                text = ctx_subject.getText() if hasattr(ctx_subject, 'getText') else ''
            prefix = fields['subject_type']
            candidate_raw = text
            if text.lower().startswith(prefix):
                candidate_raw = text[len(prefix) :].lstrip()
                logger.info(
                    f"[DEBUG] group/dynamic-group: Stripped prefix '{prefix}' from '{text}' => '{candidate_raw}'"
                )
            else:
                logger.info(f"[DEBUG] group/dynamic-group: No type prefix to strip in subject: '{text}'")
            raw_subject = candidate_raw
            logger.info(f"[DEBUG] Final raw_subject for group/dynamic-group: '{raw_subject}'")

            # --- NEW LOGIC FOR group-id/dynamic-group-id ---
            subject_items = [item.strip() for item in re.split(r',\s*', raw_subject) if item.strip()]
            all_ocid_id = all(re.match(r'^(id\s*)?ocid1\.', item, re.IGNORECASE) for item in subject_items)
            logger.info(f'[INFO] subject_items: {subject_items}')
            logger.info(f"[INFO] Detected all_ocid_id={all_ocid_id} for subject_type={fields['subject_type']}")
            if all_ocid_id:
                subtype = 'group-id' if fields['subject_type'] == 'group' else 'dynamic-group-id'
                cleaned_items = [re.sub(r'^(id\s*)', '', item, flags=re.IGNORECASE) for item in subject_items]
                canonical_subject = ', '.join(cleaned_items)
                logger.info(
                    f"[INFO] All subjects recognized as OCIDs, canonical_subject after stripping 'id': {canonical_subject}"
                )
                fields['subject_type'] = subtype
                # Final log before parse
                logger.info(
                    f'[INFO] Passing to parse_policy_subjects: subject_type={subtype}, canonical_subject={canonical_subject!r}'
                )
                result = parse_policy_subjects(subtype, canonical_subject)
                logger.info(
                    f'[INFO] Result from parse_policy_subjects: subject_type={subtype}, canonical_subject={canonical_subject!r}, result={result!r}'
                )
                fields['subject'] = result
            else:
                # Normal path, possibly named groups only
                logger.info(
                    f"[INFO] Falling back to normal parse_policy_subjects for subject_type={fields['subject_type']}, raw_subject={raw_subject!r}"
                )
                result = parse_policy_subjects(fields['subject_type'], raw_subject)
                logger.info(
                    f"[INFO] Result from parse_policy_subjects: subject_type={fields['subject_type']}, raw_subject={raw_subject!r}, result={result!r}"
                )
                fields['subject'] = result
        else:
            raw_subject = ctx_subject.getText() if ctx_subject else ''

            # Service subjects come through as "serviceX" (no delimiter) or
            # "serviceA,serviceB" in some parse shapes. Strip the leading
            # keyword before handing to parse_policy_subjects.
            if fields['subject_type'] == 'service' and raw_subject:
                raw_subject = re.sub(r'^service\s*', '', raw_subject, flags=re.IGNORECASE)
                raw_subject = re.sub(r',\s*service\s*', ',', raw_subject, flags=re.IGNORECASE)

            logger.info(
                f"[DEBUG] Non-group subject extraction: ctx_subject={ctx_subject}, subject_type={fields['subject_type']}, raw_subject={raw_subject!r}"
            )
            result = parse_policy_subjects(fields['subject_type'], raw_subject)
            logger.info(
                f"[INFO] Result from parse_policy_subjects: subject_type={fields['subject_type']}, raw_subject={raw_subject!r}, result={result!r}"
            )
            fields['subject'] = result
        verb_ctx = ctx.verb()
        resource_ctx = ctx.resource()
        plist_ctx = ctx.permissionList()
        if verb_ctx is not None:
            fields['verb'] = self._get_text(verb_ctx)
        if resource_ctx is not None:
            fields['resource'] = self._get_text(resource_ctx)
        if plist_ctx is not None:
            fields['permissionList'] = self._get_text(plist_ctx)
        fields['scope'] = self._get_text(ctx.scope())
        loc_type, loc_val = self._parse_location_from_scope(fields['scope'])
        fields['location_type'] = loc_type
        fields['location'] = loc_val

        # --- DEBUG: Log all ways of extracting the condition for diagnosis
        cond_ctx = ctx.condition()
        cond_from_gettext = cond_ctx.getText() if cond_ctx else ''
        cond_from_slice = None
        slice_start = 'N/A'
        slice_stop = 'N/A'
        if cond_ctx is not None and hasattr(cond_ctx, 'start') and hasattr(cond_ctx, 'stop') and self._input_text:
            start = cond_ctx.start.start
            stop = cond_ctx.stop.stop
            if isinstance(start, int) and isinstance(stop, int) and stop >= start:
                cond_from_slice = self._input_text[start : stop + 1]
                slice_start = start
                slice_stop = stop
        fields['condition'] = (
            cond_from_slice if cond_from_slice is not None else (self._get_text(cond_ctx) if cond_ctx else '')
        )
        if self._input_text is not None:
            statement_preview = self._input_text[:120]
        else:
            statement_preview = '<NO_INPUT_TEXT>'
        logger.debug(
            f"[Normalizer] Statement='{statement_preview}...' | "
            + f"condition.getText()='{cond_from_gettext}' | "
            + f"slice=({slice_start},{slice_stop}) -> '{cond_from_slice}' | "
            + f"final fields['condition']='{fields['condition']}'"
        )
        # --- END DEBUG

        # Parse trailing comment
        fields['comments'] = ''
        try:
            COMMENT_TYPE = getattr(PolicyLexer, 'COMMENT', 1001)
        except Exception:
            COMMENT_TYPE = 1001
        for i in range(ctx.getChildCount()):
            child = ctx.getChild(i)
            if isinstance(child, TerminalNode):
                symbol = getattr(child, 'symbol', None)
                if symbol and getattr(symbol, 'type', None) == COMMENT_TYPE:
                    comment_txt = symbol.text or ''
                    comment_txt = comment_txt.lstrip('/').lstrip('/')
                    comment_txt = comment_txt.strip()
                    fields['comments'] = comment_txt
                    break
        return fields

    def visitAdmitExpression(self, ctx):  # noqa: C901
        fields = {}
        action = self._get_action_prefix(ctx)
        fields['type'] = 'admit' if action == 'admit' else action
        fields['action'] = action

        subject_type = None
        try:
            subj_ctx = ctx.subject()
            if subj_ctx:
                if subj_ctx.groupSubject():
                    subject_type = 'group'
                elif subj_ctx.dynamicGroupSubject():
                    subject_type = 'dynamic-group'
                elif subj_ctx.serviceSubject():
                    subject_type = 'service'
                elif subj_ctx.resourceSubject():
                    subject_type = 'resource'
                elif subj_ctx.ANYUSER():
                    subject_type = 'any-user'
        except Exception:
            subject_type = ''
        fields['subject_type'] = subject_type or ''
        raw_subject = ctx.subject().getText() if ctx.subject() else ''
        fields['subject'] = parse_policy_subjects(fields['subject_type'], raw_subject)
        endorse_scopes = ctx.endorseScope()
        if endorse_scopes:
            if len(endorse_scopes) == 1:
                fields['of_endorse_scope'] = self._get_text(endorse_scopes[0])
            elif len(endorse_scopes) >= 2:
                fields['of_endorse_scope'] = self._get_text(endorse_scopes[0])
                fields['with_endorse_scope'] = self._get_text(endorse_scopes[1])
        if ctx.endorseVerb():
            fields['endorseVerb'] = self._get_text(ctx.endorseVerb())
        resource_ctx = ctx.resource()
        if resource_ctx:
            fields['resource'] = self._get_text(resource_ctx)
        plist_ctx = ctx.permissionList()
        if plist_ctx:
            fields['permissionList'] = self._get_text(plist_ctx)
        fields['scope'] = self._get_text(ctx.scope())
        loc_type, loc_val = self._parse_location_from_scope(fields['scope'])
        fields['location_type'] = loc_type
        fields['location'] = loc_val
        fields['condition'] = self._get_text(ctx.condition())
        # Parse trailing comment
        fields['comments'] = ''
        try:
            COMMENT_TYPE = getattr(PolicyLexer, 'COMMENT', 1001)
        except Exception:
            COMMENT_TYPE = 1001
        for i in range(ctx.getChildCount()):
            child = ctx.getChild(i)
            if isinstance(child, TerminalNode):
                symbol = getattr(child, 'symbol', None)
                if symbol and getattr(symbol, 'type', None) == COMMENT_TYPE:
                    comment_txt = symbol.text or ''
                    comment_txt = comment_txt.lstrip('/').lstrip('/')
                    comment_txt = comment_txt.strip()
                    fields['comments'] = comment_txt
                    break
            elif str(type(child)).endswith("COMMENTContext'>"):
                fields['comments'] = child.getText()
            elif hasattr(child, 'getText') and isinstance(child.getText(), str) and child.getText().startswith('//'):
                fields['comments'] = child.getText()
        return fields

    def visitEndorseExpression(self, ctx):  # noqa: C901
        fields = {}
        action = self._get_action_prefix(ctx)
        fields['type'] = 'endorse' if action == 'endorse' else action
        fields['action'] = action

        subject_type = None
        try:
            subj_ctx = ctx.subject()
            if subj_ctx:
                if subj_ctx.groupSubject():
                    subject_type = 'group'
                elif subj_ctx.dynamicGroupSubject():
                    subject_type = 'dynamic-group'
                elif subj_ctx.serviceSubject():
                    subject_type = 'service'
                elif subj_ctx.resourceSubject():
                    subject_type = 'resource'
                elif subj_ctx.ANYUSER():
                    subject_type = 'any-user'
        except Exception:
            subject_type = ''
        fields['subject_type'] = subject_type or ''
        raw_subject = ctx.subject().getText() if ctx.subject() else ''
        fields['subject'] = parse_policy_subjects(fields['subject_type'], raw_subject)
        if ctx.endorseVerb():
            fields['endorseVerb'] = self._get_text(ctx.endorseVerb())
        res_ctxs = ctx.resource()
        plist_ctx = ctx.permissionList()
        if res_ctxs:
            fields['resource'] = self._get_text(res_ctxs[0]) if isinstance(res_ctxs, list) else self._get_text(res_ctxs)
        if plist_ctx:
            fields['permissionList'] = self._get_text(plist_ctx)
        if ctx.endorseScope():
            first_scope = ctx.endorseScope(0)
            fields['endorseScope'] = self._get_text(first_scope)
            if ctx.endorseScope().__len__() > 1:
                resource_list = ctx.resource()
                if resource_list and len(resource_list) > 1:
                    fields['associated_resource'] = self._get_text(resource_list[1])
                fields['associated_scope'] = self._get_text(ctx.endorseScope(1))
        fields['condition'] = self._get_text(ctx.condition())
        fields['comments'] = ''
        try:
            COMMENT_TYPE = getattr(PolicyLexer, 'COMMENT', 1001)
        except Exception:
            COMMENT_TYPE = 1001
        for i in range(ctx.getChildCount()):
            child = ctx.getChild(i)
            if isinstance(child, TerminalNode):
                symbol = getattr(child, 'symbol', None)
                if symbol and getattr(symbol, 'type', None) == COMMENT_TYPE:
                    comment_txt = symbol.text or ''
                    comment_txt = comment_txt.lstrip('/').lstrip('/')
                    comment_txt = comment_txt.strip()
                    fields['comments'] = comment_txt
                    break
            elif str(type(child)).endswith("COMMENTContext'>"):
                fields['comments'] = child.getText()
            elif hasattr(child, 'getText') and isinstance(child.getText(), str) and child.getText().startswith('//'):
                fields['comments'] = child.getText()
        return fields

    def visitDefineExpression(self, ctx):  # noqa: C901
        fields = {}
        fields['type'] = 'define'
        fields['action'] = 'define'
        subj_ctx = ctx.definedSubject()
        # Group/dynamic-group/compartment/tenancy type mapping
        # Prefer feature detection on parse-context accessors over exact class
        # names, because generated ANTLR class names can vary slightly.
        if subj_ctx and hasattr(subj_ctx, 'groupSubject') and subj_ctx.groupSubject():
            fields['defined_type'] = 'group'
            names = parse_policy_subjects('group', subj_ctx.getText())
            fields['defined_name'] = names[0][1] if names else ''
        elif subj_ctx and hasattr(subj_ctx, 'dynamicGroupSubject') and subj_ctx.dynamicGroupSubject():
            fields['defined_type'] = 'dynamic-group'
            names = parse_policy_subjects('dynamic-group', subj_ctx.getText())
            fields['defined_name'] = names[0][1] if names else ''
        elif subj_ctx and hasattr(subj_ctx, 'compartmentSubject') and subj_ctx.compartmentSubject():
            fields['defined_type'] = 'compartment'
            fields['defined_name'] = subj_ctx.getChild(1).getText() if subj_ctx.getChildCount() >= 2 else ''
        elif subj_ctx and hasattr(subj_ctx, 'tenancySubject') and subj_ctx.tenancySubject():
            fields['defined_type'] = 'tenancy'
            fields['defined_name'] = subj_ctx.getChild(1).getText() if subj_ctx.getChildCount() >= 2 else ''
        else:
            # Fallback: parse best-effort from raw defined subject text.
            raw_defined_subject = self._get_text(subj_ctx).strip()
            parts = raw_defined_subject.split(None, 1)
            if len(parts) == 2 and parts[0].casefold() in {'group', 'dynamic-group', 'compartment', 'tenancy'}:
                fields['defined_type'] = parts[0].casefold()
                fields['defined_name'] = parts[1]
            else:
                fields['defined_type'] = ''
                fields['defined_name'] = raw_defined_subject
        fields['definedSubject'] = self._get_text(subj_ctx)
        fields['defined'] = self._get_text(ctx.defined())
        fields['comments'] = ''
        try:
            COMMENT_TYPE = getattr(PolicyLexer, 'COMMENT', 1001)
        except Exception:
            COMMENT_TYPE = 1001
        for i in range(ctx.getChildCount()):
            child = ctx.getChild(i)
            if isinstance(child, TerminalNode):
                symbol = getattr(child, 'symbol', None)
                if symbol and getattr(symbol, 'type', None) == COMMENT_TYPE:
                    comment_txt = symbol.text or ''
                    comment_txt = comment_txt.lstrip('/').lstrip('/')
                    comment_txt = comment_txt.strip()
                    fields['comments'] = comment_txt
                    break
            elif str(type(child)).endswith("COMMENTContext'>"):
                fields['comments'] = child.getText()
            elif hasattr(child, 'getText') and isinstance(child.getText(), str) and child.getText().startswith('//'):
                fields['comments'] = child.getText()
        return fields

    def visitPolicy(self, ctx):
        statements = []
        for child in ctx.getChildren():
            if hasattr(child, 'accept'):
                result = child.accept(self)
                if result:
                    statements.append(result)
        return statements


# The core parser class moved here:
class PolicyStatementParser:
    """
    Encapsulates OCI policy parsing using ANTLR.
    Usage:
        results = PolicyStatementParser().parse(text)
        # results: List[dict] (1 per parsed top-level policy statement)
    """

    def __init__(self):
        pass

    def parse(self, text):
        logger.debug(f'Parsing statement: {repr(text)}')
        input_stream = InputStream(text)
        lexer = PolicyLexer(input_stream)
        parser = PolicyParser(CommonTokenStream(lexer))
        lexer.removeErrorListeners()
        parser.removeErrorListeners()
        error_listener = LoggingErrorListener(logger=logger, context_text=text)
        lexer.addErrorListener(error_listener)
        parser.addErrorListener(error_listener)
        visitor = _FieldCollectingVisitor(input_text=text)
        try:
            tree = parser.policy()
            parsed = visitor.visit(tree)
            if error_listener.errors:
                for msg in error_listener.errors:
                    logger.debug(f'ANTLR parse error: {msg}')
            if error_listener.warnings:
                for msg in error_listener.warnings:
                    logger.debug(f'ANTLR parse warning: {msg}')
            logger.debug(f'Parse result (raw): {parsed}')
            if not parsed or not isinstance(parsed, list):
                logger.debug(f"Parser returned no statement objects for: '{text[:80]}...'")
            else:
                logger.debug(f'Parsed {len(parsed)} statement(s).')
            # Also return error_listener.errors alongside parsed
            return parsed, error_listener.errors
        except Exception as exc:
            logger.debug(f'Exception in PolicyStatementParser.parse: {exc}', exc_info=True)
            return None, [str(exc)]


def strip_quotes(val):
    if isinstance(val, str) and len(val) > 1:
        if (val[0] == val[-1]) and val[0] in '\'"':
            return val[1:-1]
    return val


def _extract_tenancy_aliases(*values: str) -> list[str]:
    """Extract referenced tenancy aliases from raw clause strings."""
    aliases: list[str] = []
    for value in values:
        text = str(value or '')
        for match in re.finditer(r'\btenancy\s+([^\s,{}]+)', text, flags=re.IGNORECASE):
            alias = str(match.group(1) or '').strip().strip('\'"')
            if alias:
                aliases.append(alias)
    # preserve order, remove dupes
    return list(dict.fromkeys(aliases))


def _build_unresolved_alias_map(aliases: list[str]) -> dict[str, dict[str, str | bool]]:
    """Build default unresolved alias map populated at parse time."""
    return {alias: {'alias': alias, 'ocid': '', 'resolved': False} for alias in aliases}


class PolicyStatementNormalizer:
    def __init__(self):
        self.antlr_parser = PolicyStatementParser()

    def normalize(self, statement_text: str, statement_type: str, base_fields: dict):
        """
        Normalize a statement of a given type (define/admit/endorse/regular).
        base_fields must include all fields from BasePolicyStatement required by models.
        """

        logger.debug(f"Normalizing statement of type '{statement_type}': {statement_text}")

        # Parse and also capture parse errors
        parsed_statements, parse_errors = self.antlr_parser.parse(statement_text)
        # If *any* parse_errors were present, treat this as not parsed, even if something is returned in parsed_statements.
        if parse_errors and len(parse_errors) > 0:
            logger.info(f'Parsing failed for: {statement_text} with errors: {parse_errors}')
            return {'parsed': False, 'invalid_reasons': parse_errors}
        if not parsed_statements or not isinstance(parsed_statements, list):
            logger.info(f'Parsing failed for: {statement_text} with errors: {parse_errors}')
            return {'parsed': False, 'invalid_reasons': [f'Failed to parse: {statement_text}']}

        fields = parsed_statements[0]
        st_type = statement_type.lower().strip()
        if st_type == 'define':
            return self._normalize_define(statement_text, fields, base_fields)
        elif st_type == 'admit':
            return self._normalize_admit(statement_text, fields, base_fields)
        elif st_type == 'endorse':
            return self._normalize_endorse(statement_text, fields, base_fields)
        elif st_type in ('allow', 'deny', 'regular'):
            return self._normalize_regular(statement_text, fields, base_fields)
        else:
            logger.debug(f"Unknown statement type for normalization: '{statement_type}'")
            return {'parsed': False, 'invalid_reasons': [f'Unknown statement type: {statement_type}']}

    def _normalize_define(self, statement_text, fields, base):
        # The visitor now provides explicit defined_type and defined_name
        defined_type = str(fields.get('defined_type', '') or '').strip()
        defined_name = str(fields.get('defined_name', '') or '').strip()

        # Defensive fallback for legacy parse shape where defined_name may
        # contain both parts, e.g. "tenancy aliasName".
        if not defined_type and defined_name:
            parts = defined_name.split(None, 1)
            if len(parts) == 2 and parts[0].casefold() in {'group', 'dynamic-group', 'compartment', 'tenancy'}:
                defined_type = parts[0].casefold()
                defined_name = parts[1].strip()

        # Additional fallback directly from statement text.
        if (not defined_type or not defined_name) and isinstance(statement_text, str):
            match = re.match(
                r'^\s*define\s+(group|dynamic-group|compartment|tenancy)\s+(.+?)\s+as\s+(.+?)\s*$',
                statement_text,
                re.IGNORECASE,
            )
            if match:
                defined_type = defined_type or match.group(1).casefold()
                defined_name = defined_name or match.group(2).strip()

        logger.info(f'Normalizing define statement: {statement_text}')
        logger.info(f"Extracted fields for define: defined_type='{defined_type}', defined_name='{defined_name}'")
        logger.info(f'All fields extracted by visitor: {fields}')
        obj = {
            **base,
            'defined_type': defined_type,
            'defined_name': defined_name,
            'ocid_alias': fields.get('defined', ''),
            'comment': fields.get('comments', ''),
            'parsed': True,
            'valid': True,
            'statement_text': statement_text,
        }
        return DefineStatement(**obj)

    @staticmethod
    def _subject_to_text(subject_value) -> str:
        """Normalize parsed subject payload to a stable display string.

        Parsed subject values can be lists containing tuples (domain/name)
        and/or plain strings (OCIDs, any-user, service names). Joining directly
        can raise when tuples are present, so we normalize each element first.
        """
        if isinstance(subject_value, list):
            rendered: list[str] = []
            for item in subject_value:
                if isinstance(item, tuple):
                    # Common canonical shape from parse_policy_subjects:
                    # (domain, name) where domain may be None for id subjects.
                    if len(item) >= 2:
                        domain = '' if item[0] is None else str(item[0]).strip()
                        name = str(item[1]).strip()
                        rendered.append(f'{domain}/{name}' if domain else name)
                    else:
                        rendered.append('/'.join(str(x) for x in item if x is not None))
                else:
                    rendered.append(str(item))
            return ','.join(x for x in rendered if x)
        return str(subject_value or '')

    @staticmethod
    def _subject_to_principal_keys(subject_type: str, subject_value) -> list[str]:
        """Convert parsed subject payload into canonical principal key list."""
        stype = str(subject_type or '').strip().lower()

        if not isinstance(subject_value, list):
            subject_value = [subject_value] if subject_value else []

        keys: list[str] = []
        for item in subject_value:
            if isinstance(item, tuple):
                domain = item[0] if len(item) >= 1 else None
                name = item[1] if len(item) >= 2 else ''
                if stype in {'group-id', 'dynamic-group-id'}:
                    key_type = stype
                    keys.append(f'{key_type}:{str(name).strip()}')
                else:
                    keys.append(calculate_principal_key(stype, domain, str(name)))
                continue

            value = str(item or '').strip()
            if not value:
                continue

            # For name-based group/dynamic-group entries encoded as strings
            # (typically OCIDs), generate id-style principal keys.
            if stype == 'group':
                keys.append(f'group-id:{value}')
            elif stype == 'dynamic-group':
                keys.append(f'dynamic-group-id:{value}')
            elif stype in {'group-id', 'dynamic-group-id'}:
                keys.append(f'{stype}:{value}')
            elif stype in {'any-user', 'any-group', 'service'}:
                keys.append(calculate_principal_key(stype, None, value or stype))
            else:
                keys.append(calculate_principal_key(stype, None, value))

        return list(dict.fromkeys(k for k in keys if k))

    def _normalize_admit(self, statement_text, fields, base):
        subject = self._subject_to_text(fields.get('subject', ''))
        admitted_principal_type = fields.get('subject_type', '')
        principal_keys = self._subject_to_principal_keys(admitted_principal_type, fields.get('subject', ''))
        of_tenancy_val = fields.get('of_endorse_scope', '')
        admitted_tenancy = ''
        if of_tenancy_val:
            m = re.match(r'tenancy\s*(.+)', of_tenancy_val, re.IGNORECASE)
            if m:
                admitted_tenancy = m.group(1).strip()
        perms = []
        perms_original = []
        if fields.get('permissionList'):
            perms_original = [p.strip() for p in fields['permissionList'].strip('{}').split(',') if p.strip()]
            perms = [p.upper() for p in perms_original]
        admit_action = fields.get('endorseVerb', '') or fields.get('verb', '')
        with_resource = fields.get('associated_resource', '')
        with_scope = fields.get('associated_scope', '') or fields.get('with_endorse_scope', '')
        associate_clause_raw = ''
        if str(admit_action).strip().lower() == 'associate':
            associate_clause_raw = (
                f"associate {fields.get('resource', '')} in {fields.get('scope', '')}"
                + (f' with {with_resource} in {with_scope}' if with_resource and with_scope else '')
            ).strip()

        tenancy_aliases = _extract_tenancy_aliases(of_tenancy_val, fields.get('scope', ''), with_scope)
        obj = {
            **base,
            'admit_permissions_original': perms_original,
            'action_type': fields.get('action', ''),
            'admitted_principal_type': admitted_principal_type,
            'admitted_principal': subject,
            'principal_keys': principal_keys,
            'admitted_tenancy': admitted_tenancy,
            # Back-compat alias while downstream references migrate.
            'admitted_principal_tenancy': admitted_tenancy,
            'admit_action': admit_action,
            'admit_resource': fields.get('resource', ''),
            'admit_permissions': perms,
            'admit_location_type': fields.get('location_type', ''),
            'admit_location': strip_quotes(fields.get('location', '')),
            'admit_associate_resource': fields.get('associated_resource', ''),
            'admit_associate_tenancy': fields.get('associated_scope', ''),
            'admit_associate_with_resource': with_resource,
            'admit_associate_with_tenancy': with_scope,
            'associate_clause_raw': associate_clause_raw,
            'tenancy_aliases': tenancy_aliases,
            'resolved_aliases': _build_unresolved_alias_map(tenancy_aliases),
            'aliases_resolved': False,
            'where_clause': fields.get('condition', ''),
            'comment': fields.get('comments', ''),
            'parsed': True,
            'valid': True,
            'statement_text': statement_text,
        }
        return AdmitStatement(**obj)

    def _normalize_endorse(self, statement_text, fields, base):
        subject = self._subject_to_text(fields.get('subject', ''))
        endorsed_principal_type = fields.get('subject_type', '')
        principal_keys = self._subject_to_principal_keys(endorsed_principal_type, fields.get('subject', ''))
        endorse_scope_val = fields.get('endorseScope', '')
        endorse_tenancy = ''
        if endorse_scope_val:
            if str(endorse_scope_val).strip().lower() == 'any-tenancy':
                endorse_tenancy = 'any-tenancy'
            m = re.match(r'tenancy\s*(.+)', endorse_scope_val, re.IGNORECASE)
            if m:
                endorse_tenancy = m.group(1).strip()
            if not endorse_tenancy:
                m_of = re.search(r'\bof\s+tenancy\s+([^\s,{}]+)', str(endorse_scope_val), re.IGNORECASE)
                if m_of:
                    endorse_tenancy = m_of.group(1).strip()

        perms = []
        perms_original = []
        if fields.get('permissionList'):
            perms_original = [p.strip() for p in fields['permissionList'].strip('{}').split(',') if p.strip()]
            perms = [p.upper() for p in perms_original]
        endorse_action = fields.get('endorseVerb', '') or fields.get('verb', '')
        with_resource = fields.get('associated_resource', '')
        with_scope = fields.get('associated_scope', '')
        associate_clause_raw = ''
        if str(endorse_action).strip().lower() == 'associate':
            associate_clause_raw = (
                f"associate {fields.get('resource', '')} in {fields.get('endorseScope', '')}"
                + (f' with {with_resource} in {with_scope}' if with_resource and with_scope else '')
            ).strip()

        tenancy_aliases = _extract_tenancy_aliases(fields.get('endorseScope', ''), with_scope)
        obj = {
            **base,
            'endorse_permissions_original': perms_original,
            'action_type': fields.get('action', ''),
            'endorsed_principal_type': endorsed_principal_type,
            'endorsed_principal': subject,
            'principal_keys': principal_keys,
            'endorsed_principal_tenancy': '',
            'endorse_action': endorse_action,
            'endorse_resource': fields.get('resource', ''),
            'endorse_permissions': perms,
            'endorse_tenancy': endorse_tenancy,
            'endorse_location_type': fields.get('location_type', ''),
            'endorse_location': strip_quotes(fields.get('location', '')),
            'endorse_associate_resource': fields.get('associated_resource', ''),
            'endorse_associate_tenancy': fields.get('associated_scope', ''),
            'endorse_associate_with_resource': with_resource,
            'endorse_associate_with_tenancy': with_scope,
            'associate_clause_raw': associate_clause_raw,
            'tenancy_aliases': tenancy_aliases,
            'resolved_aliases': _build_unresolved_alias_map(tenancy_aliases),
            'aliases_resolved': False,
            'where_clause': fields.get('condition', ''),
            'comment': fields.get('comments', ''),
            'parsed': True,
            'valid': True,
            'statement_text': statement_text,
        }
        return EndorseStatement(**obj)

    def _normalize_regular(self, statement_text, fields, base):
        logger.info(f'Normalizing regular policy statement: {statement_text}')
        subject_type = fields.get('subject_type', '') or ''
        subjects_out = []
        subj_raw = fields.get('subject', '')
        principal_keys = self._subject_to_principal_keys(subject_type, subj_raw)

        # Need to log both the subject_type and the raw subject value for debugging, especially for edge cases
        logger.info(f"Subject type: '{subject_type}', raw subject value: '{subj_raw}'")
        # Log all fields for diagnosis
        logger.info(f'All extracted fields for regular statement: {fields}')

        # All normalization is now handled by parse_policy_subjects; no further postprocessing needed.
        subjects_out = subj_raw
        perms = []
        perms_original = []
        if 'permissionList' in fields and fields['permissionList']:
            perms_original = [p.strip() for p in fields['permissionList'].strip('{}').split(',') if p.strip()]
            perms = [p.upper() for p in perms_original]
        existing_notes = []
        if isinstance(base, dict):
            existing_notes = list(base.get('parsing_notes') or [])
        if isinstance(fields.get('parsing_notes'), list):
            existing_notes.extend(fields.get('parsing_notes'))
        parsing_notes = list(dict.fromkeys(existing_notes))
        if isinstance(subjects_out, list) and len(subjects_out) > 1:
            parsing_notes.append('Statement has multiple subjects')

        conditions = fields.get('condition', '') or ''
        where_clause = parse_condition_structure(conditions)
        obj = {
            **base,
            # 'permission_original': perms_original,
            'action': fields.get('action', '').lower() or 'allow',
            'valid': True,
            'invalid_reasons': [],
            'subject_type': subject_type,
            'subject': subjects_out,
            'principal_keys': principal_keys,
            'verb': fields.get('verb', '') or '',
            'resource': fields.get('resource', '') or '',
            'permission': perms,
            'location_type': fields.get('location_type', ''),
            'location': strip_quotes(fields.get('location', '')),
            'conditions': conditions,
            'conditions_where_clause': conditions,
            'conditions_parsed_structure': format_condition_structure_summary(where_clause),
            'condition_atoms': where_clause.get('atoms', []),
            'where_clause': where_clause,
            'where_clause_structure': where_clause,
            'comments': fields.get('comments', ''),
            'parsing_notes': parsing_notes,
            'statement_text': statement_text,
            'parsed': True,
        }
        logger.info(f'Normalized regular policy statement object: {obj}\n')

        return RegularPolicyStatement(**obj)


# [REMOVED LEGACY] def _parse_subjects(self, subject_list): Legacy utility—replaced by parse_policy_subjects and canonical output logic.
