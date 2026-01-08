"""
condition_parser.py

Implements the ConditionParser class, which can parse and evaluate OCI policy condition strings.
"""

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from .OciIamPolicyConditionLexer import OciIamPolicyConditionLexer
from .OciIamPolicyConditionParser import OciIamPolicyConditionParser
from .OciIamPolicyConditionVisitor import OciIamPolicyConditionVisitor


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

    # Paste visitor methods here or import from shared file if necessary (not shown for brevity)
    # ... (copy unchanged from previous implementation) ...


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
        tree = parser.condition_clause()
        if parser.getNumberOfSyntaxErrors() > 0:
            return {'condition': text, 'result': 'SYNTAX ERROR', 'log': [], 'errors': error_listener.errors}
        visitor = ConditionExecutionVisitor(self.sim_vars)
        passed = visitor.visit(tree)
        return {'condition': text, 'result': 'GRANTED' if passed else 'DENIED', 'log': visitor.comparison_log}
