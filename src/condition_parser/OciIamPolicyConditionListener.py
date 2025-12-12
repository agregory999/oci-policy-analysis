# Generated from ./OciIamPolicyCondition.g4 by ANTLR 4.13.2
from antlr4 import *

if '.' in __name__:
    from .OciIamPolicyConditionParser import OciIamPolicyConditionParser
else:
    from OciIamPolicyConditionParser import OciIamPolicyConditionParser


# This class defines a complete listener for a parse tree produced by OciIamPolicyConditionParser.
class OciIamPolicyConditionListener(ParseTreeListener):
    # Enter a parse tree produced by OciIamPolicyConditionParser#condition_clause.
    def enterCondition_clause(self, ctx: OciIamPolicyConditionParser.Condition_clauseContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#condition_clause.
    def exitCondition_clause(self, ctx: OciIamPolicyConditionParser.Condition_clauseContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#condition_expression.
    def enterCondition_expression(self, ctx: OciIamPolicyConditionParser.Condition_expressionContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#condition_expression.
    def exitCondition_expression(self, ctx: OciIamPolicyConditionParser.Condition_expressionContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#condition_list.
    def enterCondition_list(self, ctx: OciIamPolicyConditionParser.Condition_listContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#condition_list.
    def exitCondition_list(self, ctx: OciIamPolicyConditionParser.Condition_listContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#single_condition.
    def enterSingle_condition(self, ctx: OciIamPolicyConditionParser.Single_conditionContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#single_condition.
    def exitSingle_condition(self, ctx: OciIamPolicyConditionParser.Single_conditionContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#variable_name.
    def enterVariable_name(self, ctx: OciIamPolicyConditionParser.Variable_nameContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#variable_name.
    def exitVariable_name(self, ctx: OciIamPolicyConditionParser.Variable_nameContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#condition_value.
    def enterCondition_value(self, ctx: OciIamPolicyConditionParser.Condition_valueContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#condition_value.
    def exitCondition_value(self, ctx: OciIamPolicyConditionParser.Condition_valueContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#literal_list.
    def enterLiteral_list(self, ctx: OciIamPolicyConditionParser.Literal_listContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#literal_list.
    def exitLiteral_list(self, ctx: OciIamPolicyConditionParser.Literal_listContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#literal_list_content.
    def enterLiteral_list_content(self, ctx: OciIamPolicyConditionParser.Literal_list_contentContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#literal_list_content.
    def exitLiteral_list_content(self, ctx: OciIamPolicyConditionParser.Literal_list_contentContext):
        pass

    # Enter a parse tree produced by OciIamPolicyConditionParser#all_or_any.
    def enterAll_or_any(self, ctx: OciIamPolicyConditionParser.All_or_anyContext):
        pass

    # Exit a parse tree produced by OciIamPolicyConditionParser#all_or_any.
    def exitAll_or_any(self, ctx: OciIamPolicyConditionParser.All_or_anyContext):
        pass


del OciIamPolicyConditionParser
