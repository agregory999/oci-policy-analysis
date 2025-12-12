# Generated from ./OciIamPolicyCondition.g4 by ANTLR 4.13.2
"""Visitor class for OCI IAM Policy Condition ANTLR parse tree."""

from antlr4 import ParseTreeVisitor

if '.' in __name__:
    from .OciIamPolicyConditionParser import OciIamPolicyConditionParser
else:
    from OciIamPolicyConditionParser import OciIamPolicyConditionParser


class OciIamPolicyConditionVisitor(ParseTreeVisitor):
    """Generic visitor for a parse tree produced by OciIamPolicyConditionParser."""

    def visitCondition_clause(self, ctx: OciIamPolicyConditionParser.Condition_clauseContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#condition_clause."""
        return self.visitChildren(ctx)

    def visitCondition_expression(self, ctx: OciIamPolicyConditionParser.Condition_expressionContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#condition_expression."""
        return self.visitChildren(ctx)

    def visitCondition_list(self, ctx: OciIamPolicyConditionParser.Condition_listContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#condition_list."""
        return self.visitChildren(ctx)

    def visitSingle_condition(self, ctx: OciIamPolicyConditionParser.Single_conditionContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#single_condition."""
        return self.visitChildren(ctx)

    def visitVariable_name(self, ctx: OciIamPolicyConditionParser.Variable_nameContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#variable_name."""
        return self.visitChildren(ctx)

    def visitCondition_value(self, ctx: OciIamPolicyConditionParser.Condition_valueContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#condition_value."""
        return self.visitChildren(ctx)

    def visitLiteral_list(self, ctx: OciIamPolicyConditionParser.Literal_listContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#literal_list."""
        return self.visitChildren(ctx)

    def visitLiteral_list_content(self, ctx: OciIamPolicyConditionParser.Literal_list_contentContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#literal_list_content."""
        return self.visitChildren(ctx)

    def visitAll_or_any(self, ctx: OciIamPolicyConditionParser.All_or_anyContext):
        """Visit a parse tree produced by OciIamPolicyConditionParser#all_or_any."""
        return self.visitChildren(ctx)


del OciIamPolicyConditionParser
