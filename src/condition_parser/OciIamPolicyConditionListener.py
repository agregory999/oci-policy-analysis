# Generated from ./OciIamPolicyCondition.g4 by ANTLR 4.13.2
"""Listener for OCI IAM Policy Condition ANTLR parse tree (auto-generated, linted for style)."""

from antlr4 import ParseTreeListener

if '.' in __name__:
    from .OciIamPolicyConditionParser import OciIamPolicyConditionParser
else:
    from OciIamPolicyConditionParser import OciIamPolicyConditionParser


class OciIamPolicyConditionListener(ParseTreeListener):
    """Listener interface for parse tree production by OciIamPolicyConditionParser."""

    def enterCondition_clause(self, ctx: OciIamPolicyConditionParser.Condition_clauseContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#condition_clause."""
        pass

    def exitCondition_clause(self, ctx: OciIamPolicyConditionParser.Condition_clauseContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#condition_clause."""
        pass

    def enterCondition_expression(self, ctx: OciIamPolicyConditionParser.Condition_expressionContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#condition_expression."""
        pass

    def exitCondition_expression(self, ctx: OciIamPolicyConditionParser.Condition_expressionContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#condition_expression."""
        pass

    def enterCondition_list(self, ctx: OciIamPolicyConditionParser.Condition_listContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#condition_list."""
        pass

    def exitCondition_list(self, ctx: OciIamPolicyConditionParser.Condition_listContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#condition_list."""
        pass

    def enterSingle_condition(self, ctx: OciIamPolicyConditionParser.Single_conditionContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#single_condition."""
        pass

    def exitSingle_condition(self, ctx: OciIamPolicyConditionParser.Single_conditionContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#single_condition."""
        pass

    def enterVariable_name(self, ctx: OciIamPolicyConditionParser.Variable_nameContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#variable_name."""
        pass

    def exitVariable_name(self, ctx: OciIamPolicyConditionParser.Variable_nameContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#variable_name."""
        pass

    def enterCondition_value(self, ctx: OciIamPolicyConditionParser.Condition_valueContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#condition_value."""
        pass

    def exitCondition_value(self, ctx: OciIamPolicyConditionParser.Condition_valueContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#condition_value."""
        pass

    def enterLiteral_list(self, ctx: OciIamPolicyConditionParser.Literal_listContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#literal_list."""
        pass

    def exitLiteral_list(self, ctx: OciIamPolicyConditionParser.Literal_listContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#literal_list."""
        pass

    def enterLiteral_list_content(self, ctx: OciIamPolicyConditionParser.Literal_list_contentContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#literal_list_content."""
        pass

    def exitLiteral_list_content(self, ctx: OciIamPolicyConditionParser.Literal_list_contentContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#literal_list_content."""
        pass

    def enterAll_or_any(self, ctx: OciIamPolicyConditionParser.All_or_anyContext):
        """Enter a parse tree produced by OciIamPolicyConditionParser#all_or_any."""
        pass

    def exitAll_or_any(self, ctx: OciIamPolicyConditionParser.All_or_anyContext):
        """Exit a parse tree produced by OciIamPolicyConditionParser#all_or_any."""
        pass


del OciIamPolicyConditionParser
