##########################################################################
# Copyright (c) 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl/
#
# TagConditionCollector.py
#
# Visitor/utility for extracting tag-based condition structure from
# OCI IAM policy where-clauses.
#
# Supports Python 3.12 and above
#
# @author: Cline AI
#
# coding: utf-8
##########################################################################

"""Tag-oriented visitor for OCI IAM condition clauses.

This module provides a small helper around the generated
``OciIamPolicyCondition`` parser/visitor that focuses **only** on
tag-based conditions. It is intentionally read-only and has no
simulation semantics; evaluation remains owned by
``WhereClauseEvaluator``.

The main entry point is :func:`collect_tag_conditions`, which accepts a
raw condition string and returns two artifacts:

* ``structure`` – a human-friendly representation of the logical
  structure, such as ``"ANY { c1, c2, ALL { c3, c4 } }"`` where
  ``cN`` are stable condition identifiers.
* ``conditions`` – a flat list of :class:`TagCondition` items describing
  the tag-based comparisons discovered in the tree.

The collector makes the following simplifying assumptions about
"tag-based" variables:

* A variable is considered tag-oriented if it starts with one of the
  known access-type prefixes and contains the substring ``".tag."``.
* The portion between ``.tag.`` and the next ``.`` is treated as the
  tag *namespace* and the remainder as the *key*.

These rules match the conventions used elsewhere in the UI and are
documented in ``CONTEXT_tag_based_access_tab.md``. The collector is
robust to syntax errors: if parsing fails, callers receive a simple
placeholder structure and an empty condition list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from antlr4 import CommonTokenStream, InputStream

from oci_policy_analysis.common.logger import get_logger
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionLexer import (
    OciIamPolicyConditionLexer,
)
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionParser import (
    OciIamPolicyConditionParser,
)
from oci_policy_analysis.logic.parsers.condition_parser.OciIamPolicyConditionVisitor import (
    OciIamPolicyConditionVisitor,
)

logger = get_logger(component="tag_condition_collector")


@dataclass(slots=True)
class TagCondition:
    """Normalized view of a single tag-based condition element.

    This model is kept small on purpose so it can be reused by both UI
    and analytics code without pulling in UI-specific concerns.

    Attributes:
        condition_id: Stable identifier (``"c1"``, ``"c2"``, ...) unique
            within a single where-clause. Used to tie into the
            human-readable structure string.
        access_type: Left-hand side variable prefix, such as
            ``"request.principal.group"`` or ``"target.resource"``.
        tag_namespace: Tag namespace derived from the variable name.
        tag_key: Tag key derived from the variable name (may contain
            further dots).
        operator: Normalized operator text (e.g. ``"="``, ``"!="``,
            ``"in"``, ``"not in"``, ``"before"``).
        value: Raw right-hand-side value or list representation, as
            extracted from the parse tree. For list-valued conditions the
            collector returns a comma-separated string representation so
            the UI can display it without additional formatting logic.
        subexpression: The textual subexpression corresponding to this
            single condition, as reconstructed from the parse tree.
    """

    condition_id: str
    access_type: str
    tag_namespace: str
    tag_key: str
    operator: str
    value: str
    subexpression: str


class _TagConditionVisitor(OciIamPolicyConditionVisitor):
    """Internal visitor that walks the ANTLR tree and collects tags.

    The visitor assigns condition identifiers in discovery order
    (pre-order traversal of the expression tree). These identifiers are
    then used to render a nested ``ANY``/``ALL`` structure string.
    """

    # Known access-type prefixes we consider for tag-based variables.
    _ACCESS_PREFIXES = (
        "request.principal.group",
        "request.principal.compartment",
        "target.resource",
        "target.resource.compartment",
    )

    def __init__(self) -> None:
        super().__init__()
        self._next_id = 1
        # Tag-condition identifiers are intentionally 1-based and
        # independent of the generic cN sequence so that each
        # where-clause starts with tc1 for its first discovered
        # tag-based condition.
        self._next_tag_id = 1
        self.conditions: list[TagCondition] = []
        # Map from structure-level cN identifiers to tag-level tcN
        # identifiers so we can render the Parsed Condition Structure
        # using tcN for tag-based conditions.
        self._struct_to_tag: dict[str, str] = {}
        # Raw structure string built during the first traversal. This
        # avoids double-walking the tree (which would otherwise allocate
        # duplicate cN/tcN identifiers and TagCondition entries).
        self._raw_structure: str = ""

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def _alloc_id(self) -> str:
        """Allocate an identifier for *any* single condition (cN).

        These IDs are used to render the overall structure string,
        regardless of whether the condition is tag-based.
        """

        cid = f"c{self._next_id}"
        self._next_id += 1
        return cid

    def _alloc_tag_id(self) -> str:
        """Allocate an identifier for *tag-based* conditions (tcN).

        These IDs are stored on TagCondition instances and surfaced in
        the UI's tag-condition detail table. The structure string will
        continue to reference the generic cN identifiers.
        """

        cid = f"tc{self._next_tag_id}"
        self._next_tag_id += 1
        return cid

    # ------------------------------------------------------------------
    # Core traversal
    # ------------------------------------------------------------------

    def visitCondition_clause(self, ctx):  # noqa: D401
        """Visit the top-level clause and build the structure string.

        We intentionally return ``None`` here to keep the signature
        compatible with the base visitor; callers should invoke
        :func:`collect_tag_conditions`, which orchestrates visiting and
        returns the final structure string built from internal helpers.
        """

        logger.info("TagConditionCollector: visiting condition_clause: %s", ctx.getText())
        # Traverse the expression tree exactly once and cache the raw
        # structure string so :func:`collect_tag_conditions` does not
        # need to re-walk the tree (which would allocate a second set of
        # cN/tcN identifiers and duplicate TagCondition entries).
        self._raw_structure = self._visit_condition_expression(ctx.condition_expression())
        return None

    # The generated visitor uses generic visitChildren by default; we
    # focus on the two key rules that determine structure and leaves.

    def _visit_condition_expression(self, ctx) -> str:
        # ``condition_expression`` is either a ``single_condition`` or an
        # ``all_or_any { condition_list }``.
        if ctx.single_condition():
            struct_id = self._visit_single_condition(ctx.single_condition())
            logger.info("TagConditionCollector: single_condition -> %s", struct_id)
            return struct_id
        if ctx.all_or_any():
            keyword = ctx.all_or_any().getText().upper()
            child_structs: list[str] = []
            for child in ctx.condition_list().condition_expression():
                child_structs.append(self._visit_condition_expression(child))
            # After child traversal, replace any structure IDs (cN)
            # that correspond to tag conditions with their tcN
            # counterparts so the final structure string uses tcN for
            # tag-based leaves.
            replaced: list[str] = []
            for s in child_structs:
                if not s:
                    continue
                mapped = self._struct_to_tag.get(s, s)
                logger.info(
                    "TagConditionCollector: mapping child struct '%s' -> '%s' (struct_to_tag=%s)",
                    s,
                    mapped,
                    self._struct_to_tag,
                )
                replaced.append(mapped)
            joined = ", ".join(replaced)
            return f"{keyword} {{ {joined} }}" if joined else f"{keyword} {{}}"
        # Fallback: if this rule shape evolves in the grammar, fall back
        # to the raw text so the structure column still shows something
        # meaningful instead of remaining blank.
        return ctx.getText()

    def _visit_single_condition(self, ctx) -> str:
        # Assign a structure-wide identifier for this *single* condition
        # so the top-level structure string can always be expressed in
        # terms of cN elements, regardless of whether the condition is
        # tag-based or not.
        struct_id = self._alloc_id()
        logger.info("TagConditionCollector: new single_condition struct_id=%s", struct_id)

        # Extract the raw subexpression text directly from context.
        subexpr = ctx.getText()

        # Determine operator, including the dedicated NOT_IN token.
        op_token = ctx.OPERATOR()
        not_in_token = getattr(ctx, "NOT_IN", lambda: None)()
        if not_in_token is not None:
            operator = "not in"
        else:
            operator = op_token.getText().lower() if op_token is not None else ""

        # Variable / tag breakdown
        #
        # The grammar exposes a primary variable via variable_name(),
        # but real-world policies sometimes place the tag-bearing
        # variable on the *right-hand side*, e.g.::
        #
        #   request.principal.id = target.resource.tag.ns.key
        #
        # To support these, we inspect both the primary variable and
        # the raw text of the first condition_value() and treat
        # whichever side looks like a tag variable as the canonical
        # tag-bearing side.
        variable_ctx = ctx.variable_name()
        lhs_var = variable_ctx.getText() if variable_ctx is not None else ""
        logger.info("TagConditionCollector: lhs_var=%r", lhs_var)

        rhs_text = ""
        try:
            if ctx.condition_value():
                value_ctx = ctx.condition_value(0)
                rhs_text = value_ctx.getText().strip()
        except Exception:  # pragma: no cover - defensive only
            rhs_text = ""
        logger.info("TagConditionCollector: rhs_text=%r", rhs_text)

        # Decide which side is the tag-bearing variable. If *both*
        # sides look like tag variables, we currently treat this as a
        # single logical tag condition, anchored on the left-hand
        # side. This avoids creating duplicated TagCondition entries
        # (tc1, tc2) for expressions such as::
        #
        #   request.principal.group.tag.ns.key = target.resource.tag.ns.key
        #
        # which are conceptually a single "match" condition.
        access_type = ns = key = ""

        lhs_access, lhs_ns, lhs_key = self._split_tag_variable(lhs_var)
        rhs_access, rhs_ns, rhs_key = self._split_tag_variable(rhs_text)

        logger.info(
            "TagConditionCollector: split_tag_variable lhs=(%r,%r,%r) rhs=(%r,%r,%r)",
            lhs_access,
            lhs_ns,
            lhs_key,
            rhs_access,
            rhs_ns,
            rhs_key,
        )

        if lhs_access and lhs_ns and lhs_key:
            access_type, ns, key = lhs_access, lhs_ns, lhs_key
        elif rhs_access and rhs_ns and rhs_key:
            access_type, ns, key = rhs_access, rhs_ns, rhs_key

        # Value(s) – normalize to a compact string representation so the
        # UI can display them directly.
        value_str = self._extract_value_string(ctx)

        # Only create TagCondition entries for tag-based variables. The
        # TagCondition carries a tcN identifier, while the overall
        # structure references the corresponding cN identifier.
        if access_type and ns and key:
            tag_id = self._alloc_tag_id()
            logger.info(
                "TagConditionCollector: creating TagCondition id=%s access_type=%r ns=%r key=%r operator=%r value=%r subexpr=%r",
                tag_id,
                access_type,
                ns,
                key,
                operator,
                value_str,
                subexpr,
            )
            tag_condition = TagCondition(
                condition_id=tag_id,
                access_type=access_type,
                tag_namespace=ns,
                tag_key=key,
                operator=operator,
                value=value_str,
                subexpression=subexpr,
            )
            self.conditions.append(tag_condition)
            # Remember that this cN in the structure corresponds to
            # a tag-based condition so we can render it as tcN in the
            # final structure string.
            self._struct_to_tag[struct_id] = tag_id
            logger.info(
                "TagConditionCollector: mapped struct_id %s -> tag_id %s (struct_to_tag=%s)",
                struct_id,
                tag_id,
                self._struct_to_tag,
            )
            return struct_id

        # Non-tag conditions still participate in structure using their
        # cN identifier; the distinction between tag and non-tag is
        # carried only in the TagCondition list.
        return struct_id

    # ------------------------------------------------------------------
    # Value/variable helpers
    # ------------------------------------------------------------------

    def _split_tag_variable(self, variable: str) -> Tuple[str, str, str]:
        """Split a full variable name into access type, namespace, key.

        For a variable such as::

            request.principal.group.tag.orcl-namespace.key-extra

        this method returns::

            ("request.principal.group", "orcl-namespace", "key-extra")

        If the variable does not match a known tag pattern, all
        components are returned as empty strings.
        """

        if ".tag." not in variable:
            return "", "", ""

        prefix, _, remainder = variable.partition(".tag.")
        if prefix not in self._ACCESS_PREFIXES:
            return "", "", ""

        # Namespace is the segment up to the next '.', key is the rest.
        if "." in remainder:
            ns, _, key = remainder.partition(".")
        else:
            ns, key = remainder, ""
        return prefix, ns, key

    def _extract_value_string(self, ctx) -> str:
        """Render the RHS value or literal list as a compact string."""

        try:
            if ctx.literal_list():
                content = ctx.literal_list().literal_list_content()
                # Children include commas; filter them out using token text
                raw_items: List[str] = []
                for child in list(content.getChildren()):
                    text = getattr(child, "getText", lambda: str(child))()
                    if text == ",":
                        continue
                    raw_items.append(self._strip_quotes(text))
                return ",".join(raw_items)

            if ctx.condition_value():
                value_ctx = ctx.condition_value(0)
                raw = value_ctx.getText().strip()
                return self._strip_quotes(raw)
        except Exception as exc:  # pragma: no cover - defensive only
            logger.info("TagConditionCollector: failed extracting value string: %s", exc, exc_info=True)
        return ""

    @staticmethod
    def _strip_quotes(value: str) -> str:
        if len(value) >= 2 and ((value[0] == "'" and value[-1] == "'") or (value[0] == '"' and value[-1] == '"')):
            return value[1:-1]
        return value


def collect_tag_conditions(condition_str: str) -> Tuple[str, List[TagCondition]]:
    """Parse ``condition_str`` and return tag structure + elements.

    Args:
        condition_str: Raw where-clause text (without surrounding
            ``where`` keyword). The helper is tolerant of leading/trailing
            whitespace and newlines.

    Returns:
        A tuple ``(structure, conditions)`` where:

        * ``structure`` is a human-readable string representation of the
          logical condition tree. If parsing fails, a simple placeholder
          of the form ``"(unparsed: <trimmed text>)"`` is returned.
        * ``conditions`` is a list of :class:`TagCondition` elements –
          possibly empty if no tag variables are present.
    """

    text = (condition_str or "").strip()
    if not text:
        return "", []

    try:
        input_stream = InputStream(text + "\n")
        lexer = OciIamPolicyConditionLexer(input_stream)
        stream = CommonTokenStream(lexer)
        parser = OciIamPolicyConditionParser(stream)
        tree = parser.condition_clause()

        visitor = _TagConditionVisitor()
        # Visit the tree to populate visitor.conditions and build the
        # raw structure string during a *single* traversal. This avoids
        # double-walking the tree, which could otherwise allocate
        # duplicate cN/tcN identifiers and TagCondition entries.
        visitor.visit(tree)

        # Use the structure computed during the first traversal. This
        # is already normalized to compact forms like "tc1" or
        # "ALL { tc1, tc2 }" thanks to the visitor's
        # _visit_condition_expression logic.
        raw_structure = getattr(visitor, "_raw_structure", "")  # type: ignore[attr-defined]

        # For callers that are specifically interested in tag-based
        # analysis (such as the Tag-based Access tab), represent
        # single-condition tag clauses directly by their tcN identifier
        # instead of the underlying cN. This makes the structure column
        # more intuitive: a simple tag comparison becomes "tc1" rather
        # than "c1".
        structure = raw_structure
        if raw_structure and not any(ch in raw_structure for ch in " {}"):
            # raw_structure is a bare identifier like "c2" or "tc1".
            # If this maps to a tag condition, rewrite it to the
            # corresponding tcN so callers see the tag-centric ID.
            struct_to_tag = getattr(visitor, "_struct_to_tag", {})  # type: ignore[attr-defined]
            structure = struct_to_tag.get(raw_structure, raw_structure)

        return structure, visitor.conditions
    except Exception as exc:  # pragma: no cover - defensive only
        logger.warning("collect_tag_conditions: parse error for %r: %s", text, exc, exc_info=True)
        trimmed = text.replace("\n", " ")
        return f"(unparsed: {trimmed[:120]})", []
