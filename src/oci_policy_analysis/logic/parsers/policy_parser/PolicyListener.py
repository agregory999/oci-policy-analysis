# Generated from Policy.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .PolicyParser import PolicyParser
else:
    from PolicyParser import PolicyParser

# This class defines a complete listener for a parse tree produced by PolicyParser.
class PolicyListener(ParseTreeListener):

    # Enter a parse tree produced by PolicyParser#policy.
    def enterPolicy(self, ctx:PolicyParser.PolicyContext):
        pass

    # Exit a parse tree produced by PolicyParser#policy.
    def exitPolicy(self, ctx:PolicyParser.PolicyContext):
        pass


    # Enter a parse tree produced by PolicyParser#allowExpression.
    def enterAllowExpression(self, ctx:PolicyParser.AllowExpressionContext):
        pass

    # Exit a parse tree produced by PolicyParser#allowExpression.
    def exitAllowExpression(self, ctx:PolicyParser.AllowExpressionContext):
        pass


    # Enter a parse tree produced by PolicyParser#endorseExpression.
    def enterEndorseExpression(self, ctx:PolicyParser.EndorseExpressionContext):
        pass

    # Exit a parse tree produced by PolicyParser#endorseExpression.
    def exitEndorseExpression(self, ctx:PolicyParser.EndorseExpressionContext):
        pass


    # Enter a parse tree produced by PolicyParser#defineExpression.
    def enterDefineExpression(self, ctx:PolicyParser.DefineExpressionContext):
        pass

    # Exit a parse tree produced by PolicyParser#defineExpression.
    def exitDefineExpression(self, ctx:PolicyParser.DefineExpressionContext):
        pass


    # Enter a parse tree produced by PolicyParser#compartmentSubject.
    def enterCompartmentSubject(self, ctx:PolicyParser.CompartmentSubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#compartmentSubject.
    def exitCompartmentSubject(self, ctx:PolicyParser.CompartmentSubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#admitExpression.
    def enterAdmitExpression(self, ctx:PolicyParser.AdmitExpressionContext):
        pass

    # Exit a parse tree produced by PolicyParser#admitExpression.
    def exitAdmitExpression(self, ctx:PolicyParser.AdmitExpressionContext):
        pass


    # Enter a parse tree produced by PolicyParser#endorseVerb.
    def enterEndorseVerb(self, ctx:PolicyParser.EndorseVerbContext):
        pass

    # Exit a parse tree produced by PolicyParser#endorseVerb.
    def exitEndorseVerb(self, ctx:PolicyParser.EndorseVerbContext):
        pass


    # Enter a parse tree produced by PolicyParser#verb.
    def enterVerb(self, ctx:PolicyParser.VerbContext):
        pass

    # Exit a parse tree produced by PolicyParser#verb.
    def exitVerb(self, ctx:PolicyParser.VerbContext):
        pass


    # Enter a parse tree produced by PolicyParser#permissionList.
    def enterPermissionList(self, ctx:PolicyParser.PermissionListContext):
        pass

    # Exit a parse tree produced by PolicyParser#permissionList.
    def exitPermissionList(self, ctx:PolicyParser.PermissionListContext):
        pass


    # Enter a parse tree produced by PolicyParser#scope.
    def enterScope(self, ctx:PolicyParser.ScopeContext):
        pass

    # Exit a parse tree produced by PolicyParser#scope.
    def exitScope(self, ctx:PolicyParser.ScopeContext):
        pass


    # Enter a parse tree produced by PolicyParser#endorseScope.
    def enterEndorseScope(self, ctx:PolicyParser.EndorseScopeContext):
        pass

    # Exit a parse tree produced by PolicyParser#endorseScope.
    def exitEndorseScope(self, ctx:PolicyParser.EndorseScopeContext):
        pass


    # Enter a parse tree produced by PolicyParser#subject.
    def enterSubject(self, ctx:PolicyParser.SubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#subject.
    def exitSubject(self, ctx:PolicyParser.SubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#groupSubject.
    def enterGroupSubject(self, ctx:PolicyParser.GroupSubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#groupSubject.
    def exitGroupSubject(self, ctx:PolicyParser.GroupSubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#resourceSubject.
    def enterResourceSubject(self, ctx:PolicyParser.ResourceSubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#resourceSubject.
    def exitResourceSubject(self, ctx:PolicyParser.ResourceSubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#serviceSubject.
    def enterServiceSubject(self, ctx:PolicyParser.ServiceSubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#serviceSubject.
    def exitServiceSubject(self, ctx:PolicyParser.ServiceSubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#groupName.
    def enterGroupName(self, ctx:PolicyParser.GroupNameContext):
        pass

    # Exit a parse tree produced by PolicyParser#groupName.
    def exitGroupName(self, ctx:PolicyParser.GroupNameContext):
        pass


    # Enter a parse tree produced by PolicyParser#resourceSubjectId.
    def enterResourceSubjectId(self, ctx:PolicyParser.ResourceSubjectIdContext):
        pass

    # Exit a parse tree produced by PolicyParser#resourceSubjectId.
    def exitResourceSubjectId(self, ctx:PolicyParser.ResourceSubjectIdContext):
        pass


    # Enter a parse tree produced by PolicyParser#serviceSubjectId.
    def enterServiceSubjectId(self, ctx:PolicyParser.ServiceSubjectIdContext):
        pass

    # Exit a parse tree produced by PolicyParser#serviceSubjectId.
    def exitServiceSubjectId(self, ctx:PolicyParser.ServiceSubjectIdContext):
        pass


    # Enter a parse tree produced by PolicyParser#groupID.
    def enterGroupID(self, ctx:PolicyParser.GroupIDContext):
        pass

    # Exit a parse tree produced by PolicyParser#groupID.
    def exitGroupID(self, ctx:PolicyParser.GroupIDContext):
        pass


    # Enter a parse tree produced by PolicyParser#dynamicGroupSubject.
    def enterDynamicGroupSubject(self, ctx:PolicyParser.DynamicGroupSubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#dynamicGroupSubject.
    def exitDynamicGroupSubject(self, ctx:PolicyParser.DynamicGroupSubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#tenancySubject.
    def enterTenancySubject(self, ctx:PolicyParser.TenancySubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#tenancySubject.
    def exitTenancySubject(self, ctx:PolicyParser.TenancySubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#definedSubject.
    def enterDefinedSubject(self, ctx:PolicyParser.DefinedSubjectContext):
        pass

    # Exit a parse tree produced by PolicyParser#definedSubject.
    def exitDefinedSubject(self, ctx:PolicyParser.DefinedSubjectContext):
        pass


    # Enter a parse tree produced by PolicyParser#defined.
    def enterDefined(self, ctx:PolicyParser.DefinedContext):
        pass

    # Exit a parse tree produced by PolicyParser#defined.
    def exitDefined(self, ctx:PolicyParser.DefinedContext):
        pass


    # Enter a parse tree produced by PolicyParser#resource.
    def enterResource(self, ctx:PolicyParser.ResourceContext):
        pass

    # Exit a parse tree produced by PolicyParser#resource.
    def exitResource(self, ctx:PolicyParser.ResourceContext):
        pass


    # Enter a parse tree produced by PolicyParser#condition.
    def enterCondition(self, ctx:PolicyParser.ConditionContext):
        pass

    # Exit a parse tree produced by PolicyParser#condition.
    def exitCondition(self, ctx:PolicyParser.ConditionContext):
        pass


    # Enter a parse tree produced by PolicyParser#comparison.
    def enterComparison(self, ctx:PolicyParser.ComparisonContext):
        pass

    # Exit a parse tree produced by PolicyParser#comparison.
    def exitComparison(self, ctx:PolicyParser.ComparisonContext):
        pass


    # Enter a parse tree produced by PolicyParser#variable.
    def enterVariable(self, ctx:PolicyParser.VariableContext):
        pass

    # Exit a parse tree produced by PolicyParser#variable.
    def exitVariable(self, ctx:PolicyParser.VariableContext):
        pass


    # Enter a parse tree produced by PolicyParser#operator.
    def enterOperator(self, ctx:PolicyParser.OperatorContext):
        pass

    # Exit a parse tree produced by PolicyParser#operator.
    def exitOperator(self, ctx:PolicyParser.OperatorContext):
        pass


    # Enter a parse tree produced by PolicyParser#value.
    def enterValue(self, ctx:PolicyParser.ValueContext):
        pass

    # Exit a parse tree produced by PolicyParser#value.
    def exitValue(self, ctx:PolicyParser.ValueContext):
        pass


    # Enter a parse tree produced by PolicyParser#valueList.
    def enterValueList(self, ctx:PolicyParser.ValueListContext):
        pass

    # Exit a parse tree produced by PolicyParser#valueList.
    def exitValueList(self, ctx:PolicyParser.ValueListContext):
        pass


    # Enter a parse tree produced by PolicyParser#listElement.
    def enterListElement(self, ctx:PolicyParser.ListElementContext):
        pass

    # Exit a parse tree produced by PolicyParser#listElement.
    def exitListElement(self, ctx:PolicyParser.ListElementContext):
        pass


    # Enter a parse tree produced by PolicyParser#timeWindow.
    def enterTimeWindow(self, ctx:PolicyParser.TimeWindowContext):
        pass

    # Exit a parse tree produced by PolicyParser#timeWindow.
    def exitTimeWindow(self, ctx:PolicyParser.TimeWindowContext):
        pass


    # Enter a parse tree produced by PolicyParser#comparisonList.
    def enterComparisonList(self, ctx:PolicyParser.ComparisonListContext):
        pass

    # Exit a parse tree produced by PolicyParser#comparisonList.
    def exitComparisonList(self, ctx:PolicyParser.ComparisonListContext):
        pass


    # Enter a parse tree produced by PolicyParser#logicalCombine.
    def enterLogicalCombine(self, ctx:PolicyParser.LogicalCombineContext):
        pass

    # Exit a parse tree produced by PolicyParser#logicalCombine.
    def exitLogicalCombine(self, ctx:PolicyParser.LogicalCombineContext):
        pass


    # Enter a parse tree produced by PolicyParser#patternMatch.
    def enterPatternMatch(self, ctx:PolicyParser.PatternMatchContext):
        pass

    # Exit a parse tree produced by PolicyParser#patternMatch.
    def exitPatternMatch(self, ctx:PolicyParser.PatternMatchContext):
        pass



del PolicyParser