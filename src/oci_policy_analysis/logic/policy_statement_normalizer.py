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

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.common.models import (
    AdmitStatement,
    DefineStatement,
    EndorseStatement,
    RegularPolicyStatement,
)
from oci_policy_analysis.logic.parsers.policy_parser.PolicyLexer import PolicyLexer
from oci_policy_analysis.logic.parsers.policy_parser.PolicyParser import PolicyParser
from oci_policy_analysis.logic.parsers.policy_parser.PolicyVisitor import PolicyVisitor

logger = get_logger(component='policy_parser')


class LoggingErrorListener(ErrorListener):
    """Custom ANTLR error listener that logs all syntax errors/warnings via the provided logger."""

    def __init__(self, logger=None, context_text=None):
        super().__init__()
        self.logger = logger or logging.getLogger('antlr')
        self.errors = []
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
        self.errors.append(msg)
        if self.logger:
            self.logger.debug(msg)

    def reportAttemptingFullContext(self, recognizer, dfa, startIndex, stopIndex, conflictingAlts, configs):
        msg = f'ANTLR attempting full context from {startIndex} to {stopIndex}.'
        self.errors.append(msg)
        if self.logger:
            self.logger.debug(msg)

    def reportContextSensitivity(self, recognizer, dfa, startIndex, stopIndex, prediction, configs):
        msg = f'ANTLR context sensitivity from {startIndex} to {stopIndex}.'
        self.errors.append(msg)
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

    def _get_subject(self, subject_ctx):  # Robust idocid1 handling, always fixes single-token cases  # noqa: C901
        def id_ocid_fix(tokens):
            # Fix all "idocid1..." tokens in the list (multi/comma separated or single)
            fixed = []
            for t in tokens:
                if t.lower().startswith('idocid1.'):
                    fixed.extend(['id', t[2:]])
                else:
                    fixed.append(t)
            return fixed

        if subject_ctx.groupSubject():
            subctx = subject_ctx.groupSubject()
            tokens = [
                subctx.getChild(i).getText()
                for i in range(1, subctx.getChildCount())
                if subctx.getChild(i).getText() != ','
            ]
            tokens = id_ocid_fix(tokens)
            if all(t == 'id' or t.lower().startswith('ocid1.') for t in tokens):
                ocids = []
                i = 0
                while i < len(tokens):
                    if tokens[i] == 'id' and i + 1 < len(tokens) and tokens[i + 1].lower().startswith('ocid1.'):
                        ocids.append(tokens[i + 1])
                        i += 2
                    else:
                        return [subctx.getText()]
                return ocids
            group_names = [t for t in tokens if t != 'id']
            return group_names
        elif subject_ctx.dynamicGroupSubject():
            subctx = subject_ctx.dynamicGroupSubject()
            tokens = [
                subctx.getChild(i).getText()
                for i in range(1, subctx.getChildCount())
                if subctx.getChild(i).getText() != ','
            ]
            tokens = id_ocid_fix(tokens)
            if all(t == 'id' or t.lower().startswith('ocid1.') for t in tokens):
                ocids = []
                i = 0
                while i < len(tokens):
                    if tokens[i] == 'id' and i + 1 < len(tokens) and tokens[i + 1].lower().startswith('ocid1.'):
                        ocids.append(tokens[i + 1])
                        i += 2
                    else:
                        return [subctx.getText()]
                return ocids
            names = [t for t in tokens if t != 'id']
            return names
        elif subject_ctx.resourceSubject():
            subctx = subject_ctx.resourceSubject()
            res_ids = []
            res_ids.append(subctx.getChild(1).getText())
            for i in range(2, subctx.getChildCount()):
                text = subctx.getChild(i).getText()
                if text != ',':
                    res_ids.append(text)
            return res_ids
        elif subject_ctx.serviceSubject():
            subctx = subject_ctx.serviceSubject()
            svc = []
            svc.append(subctx.getChild(1).getText())
            for i in range(2, subctx.getChildCount()):
                text = subctx.getChild(i).getText()
                if text != ',':
                    svc.append(text)
            return svc
        elif hasattr(subject_ctx, 'ANYGROUP') and subject_ctx.ANYGROUP():
            # Support for "any-group"
            return ['any-group']
        elif subject_ctx.ANYUSER():
            return ['any-user']
        else:
            return [subject_ctx.getText()]

    def visitAllowExpression(self, ctx):  # noqa: C901
        fields = {}
        action = self._get_action_prefix(ctx)
        fields['type'] = 'allow' if action == 'allow' else action
        fields['action'] = action

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

        fields['subject'] = self._get_subject(ctx.subject())
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
        fields['subject'] = self._get_subject(ctx.subject())
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
        fields['subject'] = self._get_subject(ctx.subject())
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

    def visitDefineExpression(self, ctx):
        fields = {}
        fields['type'] = 'define'
        fields['action'] = 'define'
        fields['definedSubject'] = self._get_text(ctx.definedSubject())
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
            logger.debug(f'Parsing failed for: {statement_text}')
            return {'parsed': False, 'invalid_reasons': parse_errors}
        if not parsed_statements or not isinstance(parsed_statements, list):
            logger.debug(f'Parsing failed for: {statement_text}')
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
        defined_subject = fields.get('definedSubject', '')
        defined_type = ''
        defined_name = ''
        if defined_subject:
            m = re.match(r'^(tenancy|compartment|group|dynamic-group|user)(.+)$', defined_subject, re.IGNORECASE)
            if m:
                defined_type = m.group(1).lower()
                defined_name = m.group(2)
            else:
                defined_type = ''
                defined_name = defined_subject
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

    def _normalize_admit(self, statement_text, fields, base):
        subject = (
            ','.join(fields.get('subject', []))
            if isinstance(fields.get('subject', []), list)
            else fields.get('subject', '')
        )
        admitted_principal_type = fields.get('subject_type', '')
        of_tenancy_val = fields.get('of_endorse_scope', '')
        admitted_principal_tenancy = ''
        if of_tenancy_val:
            m = re.match(r'tenancy\s*(.+)', of_tenancy_val, re.IGNORECASE)
            if m:
                admitted_principal_tenancy = m.group(1).strip()
        perms = []
        perms_original = []
        if fields.get('permissionList'):
            perms_original = [p.strip() for p in fields['permissionList'].strip('{}').split(',') if p.strip()]
            perms = [p.upper() for p in perms_original]
        obj = {
            **base,
            'admit_permissions_original': perms_original,
            'action_type': fields.get('action', ''),
            'admitted_principal_type': admitted_principal_type,
            'admitted_principal': subject,
            'admitted_principal_tenancy': admitted_principal_tenancy,
            'admit_action': fields.get('endorseVerb', '') or fields.get('verb', ''),
            'admit_resource': fields.get('resource', ''),
            'admit_permissions': perms,
            'admit_location_type': fields.get('location_type', ''),
            'admit_location': strip_quotes(fields.get('location', '')),
            'admit_associate_resource': fields.get('associated_resource', ''),
            'admit_associate_tenancy': fields.get('associated_scope', ''),
            'where_clause': fields.get('condition', ''),
            'comment': fields.get('comments', ''),
            'parsed': True,
            'valid': True,
            'statement_text': statement_text,
        }
        return AdmitStatement(**obj)

    def _normalize_endorse(self, statement_text, fields, base):
        subject = (
            ','.join(fields.get('subject', []))
            if isinstance(fields.get('subject', []), list)
            else fields.get('subject', '')
        )
        endorsed_principal_type = fields.get('subject_type', '')
        endorse_scope_val = fields.get('endorseScope', '')
        endorse_tenancy = ''
        if endorse_scope_val:
            m = re.match(r'tenancy\s*(.+)', endorse_scope_val, re.IGNORECASE)
            if m:
                endorse_tenancy = m.group(1).strip()

        perms = []
        perms_original = []
        if fields.get('permissionList'):
            perms_original = [p.strip() for p in fields['permissionList'].strip('{}').split(',') if p.strip()]
            perms = [p.upper() for p in perms_original]
        obj = {
            **base,
            'endorse_permissions_original': perms_original,
            'action_type': fields.get('action', ''),
            'endorsed_principal_type': endorsed_principal_type,
            'endorsed_principal': subject,
            'endorsed_principal_tenancy': '',
            'endorse_action': fields.get('endorseVerb', '') or fields.get('verb', ''),
            'endorse_resource': fields.get('resource', ''),
            'endorse_permissions': perms,
            'endorse_tenancy': endorse_tenancy,
            'endorse_location_type': fields.get('location_type', ''),
            'endorse_location': strip_quotes(fields.get('location', '')),
            'endorse_associate_resource': fields.get('associated_resource', ''),
            'endorse_associate_tenancy': fields.get('associated_scope', ''),
            'where_clause': fields.get('condition', ''),
            'comment': fields.get('comments', ''),
            'parsed': True,
            'valid': True,
            'statement_text': statement_text,
        }
        return EndorseStatement(**obj)

    def _normalize_regular(self, statement_text, fields, base):
        logger.debug(f'Normalizing regular policy statement: {statement_text}')
        subject_type = fields.get('subject_type', '') or ''
        subjects_out = []
        subj_raw = fields.get('subject', '')

        # If it's any-user or any-group, treat just like the original code (None, x)
        if subject_type in ['any-user', 'any-group', 'service']:
            subjects_out = [(None, subj_raw if isinstance(subj_raw, str) else subj_raw[0] if subj_raw else '')]
        # If it's a list of all OCIDs (all items are ocid1...), pass them as str to be resolved by the data repo
        elif isinstance(subj_raw, list) and all(
            isinstance(s, str) and s.lower().startswith('ocid1.') for s in subj_raw
        ):
            subjects_out = subj_raw
        elif isinstance(subj_raw, list):
            # If list but not OCIDs, treat as name-based
            subjects_out = self._parse_subjects(subj_raw)
        else:
            # fallback for edge cases (name as string)
            subjects_out = self._parse_subjects(subj_raw)
        perms = []
        perms_original = []
        if 'permissionList' in fields and fields['permissionList']:
            perms_original = [p.strip() for p in fields['permissionList'].strip('{}').split(',') if p.strip()]
            perms = [p.upper() for p in perms_original]
        obj = {
            **base,
            # 'permission_original': perms_original,
            'action': fields.get('action', '').lower() or 'allow',
            'valid': True,
            'invalid_reasons': [],
            'subject_type': subject_type,
            'subject': subjects_out,
            'verb': fields.get('verb', '') or '',
            'resource': fields.get('resource', '') or '',
            'permission': perms,
            'location_type': fields.get('location_type', ''),
            'location': strip_quotes(fields.get('location', '')),
            'conditions': fields.get('condition', '') or '',
            'comments': fields.get('comments', ''),
            'parsing_notes': ['Statement has multiple subjects']
            if isinstance(subjects_out, list) and len(subjects_out) > 1
            else [],
            'statement_text': statement_text,
            'parsed': True,
        }
        logger.debug(f'Normalized regular policy statement object: {obj}')

        return RegularPolicyStatement(**obj)

    def _parse_subjects(self, subject_list):
        """Utility for splitting subject strings for regular policies."""
        results = []
        if not isinstance(subject_list, list):
            subject_list = [subject_list]
        for subj in subject_list:
            if not subj:
                continue
            # If already an OCID string, don't treat as name-based
            if isinstance(subj, str) and subj.lower().startswith('ocid1.'):
                results.append(subj)
                continue
            s = str(subj).strip().strip('\'"')
            if '/' in s:
                domain, subject = s.split('/', 1)
                domain = domain.strip('\'"')
                subject = subject.strip('\'"')
                results.append((domain, subject))
            else:
                results.append(('default', s.strip('\'"')))
        return results
