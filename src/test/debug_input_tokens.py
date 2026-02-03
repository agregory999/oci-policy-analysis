from antlr4 import InputStream
from oci_policy_analysis.logic.parsers.policy_parser.PolicyLexer import PolicyLexer


def debug_tokens_for_policy(policy_text):
    input_stream = InputStream(policy_text)
    lexer = PolicyLexer(input_stream)
    tokens = []
    while True:
        t = lexer.nextToken()
        if t.type == -1:  # EOF
            break
        # Print token type number and text (workaround for IndexError)
        tokens.append((t.type, t.text))
    print(tokens)


# Then call with your failing policy string:
debug_tokens_for_policy(
    'allow dynamic-group id ocid1.dynamicgroup.oc1..aaa..., id ocid1.dynamicgroup.oc1..bbb... to inspect ...'
)
