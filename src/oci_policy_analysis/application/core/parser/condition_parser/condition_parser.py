"""High-level ConditionParser wrapper for OCI IAM policy where-clauses.

Application-core ownership location for the condition parser orchestration
entrypoint. Evaluation semantics are delegated to
``WhereClauseEvaluator.evaluate_where_clause`` so tests, simulation, and UI
condition checking share one canonical implementation path.
"""

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionLexer import (
    OciIamPolicyConditionLexer,
)
from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionParser import (
    OciIamPolicyConditionParser,
)
from oci_policy_analysis.application.core.parser.condition_parser.OciIamPolicyConditionVisitor import (
    OciIamPolicyConditionVisitor,
)
from oci_policy_analysis.application.core.parser.condition_parser.WhereClauseEvaluator import evaluate_where_clause


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
    # avoid breaking external imports that may still reference this class.
    pass


class ConditionParser:
    """Parser/evaluator for policy condition expressions."""

    def __init__(self, simulated_variables):
        self.sim_vars = simulated_variables

    def parse(self, text: str):
        input_stream = InputStream(text + '\n')
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

        passed, log = evaluate_where_clause(text, self.sim_vars)
        return {
            'condition': text,
            'result': 'GRANTED' if passed else 'DENIED',
            'log': log,
            'errors': [],
        }


def debug_dump_parsed_clause(condition_str: str):  # pragma: no cover - debug helper
    input_stream = InputStream(condition_str + '\n')
    lexer = OciIamPolicyConditionLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = OciIamPolicyConditionParser(stream)
    tree = parser.condition_clause()

    print('=== DEBUG PARSED CLAUSE ===')
    print(f'Condition: {condition_str!r}')
    print('Full tree:', tree.toStringTree(recog=parser))

    try:
        expr = tree.condition_expression()
        single = expr.single_condition()
        if single and single.literal_list():
            lst = single.literal_list().literal_list_content()
            children = list(lst.getChildren())
            print('literal_list_content children (type, text):')
            for c in children:
                text_getter = getattr(c, 'getText', None)
                text_value = text_getter() if callable(text_getter) else c
                print('  -', type(c).__name__, repr(text_value))
    except Exception as ex:
        print('[debug_dump_parsed_clause] Exception while introspecting tree:', ex)
