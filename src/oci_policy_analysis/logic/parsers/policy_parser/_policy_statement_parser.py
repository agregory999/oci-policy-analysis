from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from .PolicyLexer import PolicyLexer
from .PolicyParser import PolicyParser
from .PolicyVisitor import PolicyVisitor

import logging
import re

class LoggingErrorListener(ErrorListener):
    """Custom ANTLR error listener that logs all syntax errors/warnings via Python logging."""

    def __init__(self, logger=None, context_text=None):
        super().__init__()
        self.logger = logger or logging.getLogger("antlr")
        self.errors = []
        self.context_text = context_text

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        line_info = f"at line {line}, column {column}"
        context = f" while parsing: {self.context_text!r}" if self.context_text else ""
        full_msg = f"ANTLR syntax error {line_info}{context}: {msg}"
        self.errors.append(full_msg)
        if self.logger:
            self.logger.warning(full_msg)

    def reportAmbiguity(self, recognizer, dfa, startIndex, stopIndex, exact, ambigAlts, configs):
        msg = f"ANTLR ambiguity from {startIndex} to {stopIndex}."
        self.errors.append(msg)
        if self.logger:
            self.logger.warning(msg)

    def reportAttemptingFullContext(self, recognizer, dfa, startIndex, stopIndex, conflictingAlts, configs):
        msg = f"ANTLR attempting full context from {startIndex} to {stopIndex}."
        self.errors.append(msg)
        if self.logger:
            self.logger.warning(msg)

    def reportContextSensitivity(self, recognizer, dfa, startIndex, stopIndex, prediction, configs):
        msg = f"ANTLR context sensitivity from {startIndex} to {stopIndex}."
        self.errors.append(msg)
        if self.logger:
            self.logger.warning(msg)

class _FieldCollectingVisitor(PolicyVisitor):
    def __init__(self, input_text=None):
        super().__init__()
        self._input_text = input_text

    def _get_text(self, ctx_child):
        if ctx_child is None:
            return ""
        if hasattr(ctx_child, "start") and hasattr(ctx_child, "stop") and self._input_text:
            start = ctx_child.start.start
            stop = ctx_child.stop.stop
            if isinstance(start, int) and isinstance(stop, int) and stop >= start:
                return self._input_text[start:stop+1]
        if isinstance(ctx_child, list):
            if len(ctx_child) == 0:
                return ""
            return ctx_child[0].getText()
        return ctx_child.getText()

    def _parse_location_from_scope(self, scope_str):
        """Given a scope string, return (location_type, location)"""
        # Remove extra whitespace and lowercase
        if not scope_str or not isinstance(scope_str, str):
            return ("", "")
        scope = scope_str.strip()
        lower_scope = scope.lower()
        # Compartment OCID pattern (typical OCI compartment id)
        compartment_ocid_pattern = r"ocid1\.compartment\..+"
        tenancy_ocid_pattern = r"ocid1\.tenancy\..+"

        # If it's just 'tenancy' or ends with '.tenancy' or matches tenancy ocid
        if lower_scope == "tenancy":
            return ("tenancy", "tenancy")
        # Examples: compartmentidocid1.compartment.xx.yy.zz
        if lower_scope.startswith("compartmentid"):
            # Compartment OCID followed by possible path: compartmentid{ocid1.compartment.x}/compartment/xyz
            # OCID pattern: ocid1.compartment.{anything}
            match = re.match(r"compartmentid(ocid1\.compartment\.[a-zA-Z0-9.\-]+|ocid1\.tenancy\.[a-zA-Z0-9.\-]+)(?:[.:](.*))?$", scope, re.IGNORECASE)
            if match:
                ocid = match.group(1)
                trail = match.group(2)
                # If the OCID is a tenancy OCID
                if re.match(tenancy_ocid_pattern, ocid):
                    return ("tenancy", "")
                if re.match(compartment_ocid_pattern, ocid):
                    if trail and ("tenancy" in trail.lower()):
                        # e.g. compartmentid{ocid1.compartment.x}.tenancy..., treat as tenancy override
                        return ("tenancy", ocid)
                    elif trail:
                        # compartmentid{ocid1.compartment.x}.compartment.xx.yy
                        return ("compartment id", ocid)
                    else:
                        # Just the OCID
                        return ("compartment id", ocid)
                else:
                    # Not an OCID, fallback
                    return ("compartment id", ocid)
            else:
                # Not parsing? fallback
                return ("compartment id", scope)
        # Handles: "compartment id {OCID}"
        compid_match = re.match(r"compartment\s*id\s+(ocid1\.(?:compartment|tenancy)\.[a-zA-Z0-9.\-]+)", lower_scope)
        if compid_match:
            ocid = compid_match.group(1)
            # If tenancy OCID, treat as tenancy
            if re.match(tenancy_ocid_pattern, ocid):
                return ("tenancy", "")
            return ("compartment id", ocid)
        # Pure OCID? (standalone OCID string)
        if re.match(compartment_ocid_pattern, scope):
            return ("compartment id", scope)
        if re.match(tenancy_ocid_pattern, scope):
            return ("tenancy", scope)
        # If the scope contains "tenancy" (e.g., root.tenancy, or compartmentidXXX.tenancy)
        if "tenancy" in lower_scope:
            # Extract after the last 'tenancy' . or :
            parts = re.split(r"[.:]", scope)
            try:
                idx = [p.lower() for p in parts].index("tenancy")
                value = parts[idx+1] if idx+1 < len(parts) else "tenancy"
                return ("tenancy", value)
            except Exception:
                return ("tenancy", scope)
        # If the scope starts with "compartment"
        if lower_scope.startswith("compartment") and not lower_scope.startswith("compartmentid"):
            # Remove leading "compartment" and ".", ":", or whitespace, but preserve hierarchy
            match = re.match(r"compartment[.:]?(.*)", scope, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Return the full path (colons or dots) as location
                return ("compartment", name)
            else:
                return ("compartment", scope)
        # If it's a path with "." or ":", treat as compartment path (use last part as name)
        if "." in scope or ":" in scope:
            last = re.split(r"[.:]", scope)[-1]
            return ("compartment", last.strip())
        # Otherwise, treat as compartment name
        return ("compartment", scope.strip())
    def _get_action_prefix(self, ctx):
        """
        Get the action for this expression: allow, deny, admit, deny admit, endorse, deny endorse, etc.
        We scan the sequence of action tokens from ctx's children in order.
        """
        tokens = []
        for i in range(ctx.getChildCount()):
            child = ctx.getChild(i)
            txt = child.getText().lower()
            # Only include action tokens and skip others.
            # Valid first tokens: "allow", "deny", "admit", "endorse"
            if txt in ("allow", "deny", "admit", "endorse"):
                tokens.append(txt)
            else:
                # Stop at first non-action word (e.g., group/subject)
                break
        return " ".join(tokens) if tokens else ""

    def _get_subject(self, subject_ctx):
        if subject_ctx.groupSubject():
            subctx = subject_ctx.groupSubject()
            group_names = []
            group_names.append(subctx.getChild(1).getText())
            for i in range(2, subctx.getChildCount()):
                text = subctx.getChild(i).getText()
                if text != ',':
                    group_names.append(text)
            return group_names
        elif subject_ctx.dynamicGroupSubject():
            subctx = subject_ctx.dynamicGroupSubject()
            names = []
            names.append(subctx.getChild(1).getText())
            for i in range(2, subctx.getChildCount()):
                text = subctx.getChild(i).getText()
                if text != ',':
                    names.append(text)
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
        elif subject_ctx.ANYUSER():
            return ["any-user"]
        else:
            return [subject_ctx.getText()]

    def visitAllowExpression(self, ctx):
        fields = {}
        action = self._get_action_prefix(ctx)
        fields['type'] = 'allow' if action == "allow" else action
        fields['action'] = action

        # Subject type extraction: allow <subject-type> <subject> ...
        # subject_type is always the first child after the allow/deny token(s)
        # e.g. allow group Admins ...; ctx.getChild(1) is 'group', ctx.getChild(2) is subject(s)
        subject_type = None
        # Defensive: check for valid index
        try:
            first_token = ctx.getChild(0).getText().lower()  # allow/deny
            candidate = ctx.getChild(1).getText().lower() if ctx.getChildCount() > 1 else ''
            # known types in grammar: group, dynamic-group, service, any-user, any-group, resource
            if candidate in ('group', 'dynamic-group', 'service', 'any-user', 'any-group', 'resource'):
                subject_type = candidate
            else:
                # fallback: try the subject node rule context name
                subj_ctx = ctx.subject()
                if subj_ctx:
                    if subj_ctx.groupSubject(): subject_type = 'group'
                    elif subj_ctx.dynamicGroupSubject(): subject_type = 'dynamic-group'
                    elif subj_ctx.serviceSubject(): subject_type = 'service'
                    elif subj_ctx.resourceSubject(): subject_type = 'resource'
                    elif subj_ctx.ANYUSER(): subject_type = 'any-user'
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
        # Extract and add location_type/location directly
        loc_type, loc_val = self._parse_location_from_scope(fields['scope'])
        fields['location_type'] = loc_type
        fields['location'] = loc_val
        fields['condition'] = self._get_text(ctx.condition())
        fields['scope'] = self._get_text(ctx.scope())
        loc_type, loc_val = self._parse_location_from_scope(fields['scope'])
        fields['location_type'] = loc_type
        fields['location'] = loc_val
        fields['condition'] = self._get_text(ctx.condition())
        # Parse trailing comment
        fields['comments'] = ''
        from antlr4.tree.Tree import TerminalNode
        try:
            from .PolicyLexer import PolicyLexer
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

    def visitAdmitExpression(self, ctx):
        fields = {}
        action = self._get_action_prefix(ctx)
        fields['type'] = 'admit' if action == "admit" else action
        fields['action'] = action
        # Add subject_type extraction, mimicking logic from visitAllowExpression:
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
        from antlr4.tree.Tree import TerminalNode
        try:
            from .PolicyLexer import PolicyLexer
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

    def visitEndorseExpression(self, ctx):
        fields = {}
        action = self._get_action_prefix(ctx)
        fields['type'] = 'endorse' if action == "endorse" else action
        fields['action'] = action
        # Add subject_type extraction (mimic logic from visitAllowExpression):
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
        # First resource after the verb (if present)
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
        # Parse trailing comment
        fields['comments'] = ''
        from antlr4.tree.Tree import TerminalNode
        try:
            from .PolicyLexer import PolicyLexer
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
        # Parse trailing comment
        fields['comments'] = ''
        from antlr4.tree.Tree import TerminalNode
        try:
            from .PolicyLexer import PolicyLexer
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

class PolicyStatementParser:
    """
    Encapsulates OCI policy parsing using ANTLR.
    Usage:
        results = PolicyStatementParser().parse(text)
        # results: List[dict] (1 per parsed top-level policy statement)
    """
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger("antlr")

    def parse(self, text):
        input_stream = InputStream(text)
        lexer = PolicyLexer(input_stream)
        parser = PolicyParser(CommonTokenStream(lexer))

        # Remove default listeners to prevent ANTLR messages to stderr/stdout
        lexer.removeErrorListeners()
        parser.removeErrorListeners()
        # Attach our logging error listener
        error_listener = LoggingErrorListener(logger=self.logger, context_text=text)
        lexer.addErrorListener(error_listener)
        parser.addErrorListener(error_listener)

        tree = parser.policy()
        visitor = _FieldCollectingVisitor(input_text=text)
        parsed = visitor.visit(tree)
        # Only log if there were one or more ANTLR warnings/errors
        if error_listener.errors:
            for msg in error_listener.errors:
                if self.logger:
                    self.logger.warning(msg)
        return parsed
