# Generated from ./OciIamPolicyCondition.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .OciIamPolicyConditionParser import OciIamPolicyConditionParser
else:
    from OciIamPolicyConditionParser import OciIamPolicyConditionParser

# This class defines a complete generic visitor for a parse tree produced by OciIamPolicyConditionParser.

class OciIamPolicyConditionVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by OciIamPolicyConditionParser#condition_clause.
    def visitCondition_clause(self, ctx:OciIamPolicyConditionParser.Condition_clauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#condition_expression.
    def visitCondition_expression(self, ctx:OciIamPolicyConditionParser.Condition_expressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#condition_list.
    def visitCondition_list(self, ctx:OciIamPolicyConditionParser.Condition_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#single_condition.
    def visitSingle_condition(self, ctx:OciIamPolicyConditionParser.Single_conditionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#variable_name.
    def visitVariable_name(self, ctx:OciIamPolicyConditionParser.Variable_nameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#condition_value.
    def visitCondition_value(self, ctx:OciIamPolicyConditionParser.Condition_valueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#literal_list.
    def visitLiteral_list(self, ctx:OciIamPolicyConditionParser.Literal_listContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#literal_list_content.
    def visitLiteral_list_content(self, ctx:OciIamPolicyConditionParser.Literal_list_contentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by OciIamPolicyConditionParser#all_or_any.
    def visitAll_or_any(self, ctx:OciIamPolicyConditionParser.All_or_anyContext):
        return self.visitChildren(ctx)



del OciIamPolicyConditionParser