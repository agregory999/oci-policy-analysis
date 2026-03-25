"""condition_parser.py

High-level ConditionParser wrapper for OCI IAM policy where-clauses.

This module now delegates *all* evaluation to the shared
WhereClauseEvaluator/evaluate_where_clause helper so that:

* Unit tests (test_condition_parser.py)
* The Condition Tester tab
* The Simulation engine

all share one canonical implementation for condition semantics
(`=`, `!=`, `in`, time operators, tag-based variables, etc.).

The original ANTLR visitor (ConditionExecutionVisitor) is no longer
used for evaluation; it is kept only for backwards compatibility if
other callers imported it directly. New code should rely on
ConditionParser.parse() or evaluate_where_clause() instead.
"""

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from .OciIamPolicyConditionLexer import OciIamPolicyConditionLexer
from .OciIamPolicyConditionParser import OciIamPolicyConditionParser
from .OciIamPolicyConditionVisitor import OciIamPolicyConditionVisitor
from .WhereClauseEvaluator import evaluate_where_clause


class CapturingErrorListener(ErrorListener):
    def __init__(self):
        super().__init__()
        self.errors = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(
            {
                'line': line,
                'column': column,
                'msg': msg,
                'symbol': str(offendingSymbol),
            }
        )


class ConditionExecutionVisitor(OciIamPolicyConditionVisitor):
    def __init__(self, simulated_variables):
        self.simulated_variables = simulated_variables
        self.comparison_log = []

    # Legacy placeholder – no longer used for evaluation. Kept only to
    # avoid breaking external imports that may still reference this
    # class directly. All new evaluation is performed by
    # WhereClauseEvaluator via evaluate_where_clause().
    pass


class ConditionParser:
    """Parser/evaluator for policy condition expressions."""

    def __init__(self, simulated_variables):
        self.sim_vars = simulated_variables

    def parse(self, text: str):
        """Parse and evaluate a condition string using the shared evaluator.

        Returns a dict of the form::

            {
              'condition': <original text>,
              'result': 'GRANTED' | 'DENIED' | 'SYNTAX ERROR',
              'log': [ ... structured comparison entries ... ],
              'errors': [... optional syntax errors ...],
            }

        This keeps the external contract of ConditionParser.parse()
        while delegating semantics to WhereClauseEvaluator so tests,
        simulation, and the Condition Tester tab all stay in sync.
        """

        # First, run the ANTLR parser with an error listener so we can
        # surface syntax errors explicitly.
        input_stream = InputStream(text + "\n")
        lexer = OciIamPolicyConditionLexer(input_stream)
        stream = CommonTokenStream(lexer)
        parser = OciIamPolicyConditionParser(stream)
        error_listener = CapturingErrorListener()
        parser.removeErrorListeners()
        parser.addErrorListener(error_listener)
        _ = parser.condition_clause()

        if parser.getNumberOfSyntaxErrors() > 0:
            return {
                'condition': text,
                'result': 'SYNTAX ERROR',
                'log': [],
                'errors': error_listener.errors,
            }

        # Delegate evaluation to the shared WhereClauseEvaluator helper.
        passed, log = evaluate_where_clause(text, self.sim_vars)
        return {
            'condition': text,
            'result': 'GRANTED' if passed else 'DENIED',
            'log': log,
            'errors': [],
        }


def debug_dump_parsed_clause(condition_str: str):  # pragma: no cover - debug helper
    """Debug helper: print a structured view of the parsed where-clause.

    Useful when tuning semantics for operators like IN/NOT IN and pattern
    handling; shows how ANTLR tokenizes literal lists and values.
    """

    input_stream = InputStream(condition_str + "\n")
    lexer = OciIamPolicyConditionLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = OciIamPolicyConditionParser(stream)
    tree = parser.condition_clause()

    print("=== DEBUG PARSED CLAUSE ===")
    print(f"Condition: {condition_str!r}")
    print("Full tree:", tree.toStringTree(recog=parser))

    try:
        expr = tree.condition_expression()
        single = expr.single_condition()
        if single and single.literal_list():
            lst = single.literal_list().literal_list_content()
            children = list(lst.getChildren())
            print("literal_list_content children (type, text):")
            for c in children:
                print("  -", type(c).__name__, repr(getattr(c, 'getText', lambda: c)()))
    except Exception as ex:
        print("[debug_dump_parsed_clause] Exception while introspecting tree:", ex)
