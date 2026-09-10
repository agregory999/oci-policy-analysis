# Generated from Policy.g4 by ANTLR 4.13.2
from antlr4 import *

if "." in __name__:
    from .PolicyParser import PolicyParser
else:
    from PolicyParser import PolicyParser

# This class defines a complete generic visitor for a parse tree produced by PolicyParser.

class PolicyVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by PolicyParser#policy.
    def visitPolicy(self, ctx:PolicyParser.PolicyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#allowExpression.
    def visitAllowExpression(self, ctx:PolicyParser.AllowExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#endorseExpression.
    def visitEndorseExpression(self, ctx:PolicyParser.EndorseExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#defineExpression.
    def visitDefineExpression(self, ctx:PolicyParser.DefineExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#compartmentSubject.
    def visitCompartmentSubject(self, ctx:PolicyParser.CompartmentSubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#admitExpression.
    def visitAdmitExpression(self, ctx:PolicyParser.AdmitExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#endorseVerb.
    def visitEndorseVerb(self, ctx:PolicyParser.EndorseVerbContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#verb.
    def visitVerb(self, ctx:PolicyParser.VerbContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#permissionList.
    def visitPermissionList(self, ctx:PolicyParser.PermissionListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#scope.
    def visitScope(self, ctx:PolicyParser.ScopeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#endorseScope.
    def visitEndorseScope(self, ctx:PolicyParser.EndorseScopeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#subject.
    def visitSubject(self, ctx:PolicyParser.SubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#groupSubject.
    def visitGroupSubject(self, ctx:PolicyParser.GroupSubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#resourceSubject.
    def visitResourceSubject(self, ctx:PolicyParser.ResourceSubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#serviceSubject.
    def visitServiceSubject(self, ctx:PolicyParser.ServiceSubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#groupName.
    def visitGroupName(self, ctx:PolicyParser.GroupNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#resourceSubjectId.
    def visitResourceSubjectId(self, ctx:PolicyParser.ResourceSubjectIdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#serviceSubjectId.
    def visitServiceSubjectId(self, ctx:PolicyParser.ServiceSubjectIdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#groupID.
    def visitGroupID(self, ctx:PolicyParser.GroupIDContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#dynamicGroupSubject.
    def visitDynamicGroupSubject(self, ctx:PolicyParser.DynamicGroupSubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#tenancySubject.
    def visitTenancySubject(self, ctx:PolicyParser.TenancySubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#definedSubject.
    def visitDefinedSubject(self, ctx:PolicyParser.DefinedSubjectContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#defined.
    def visitDefined(self, ctx:PolicyParser.DefinedContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#resource.
    def visitResource(self, ctx:PolicyParser.ResourceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#condition.
    def visitCondition(self, ctx:PolicyParser.ConditionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#unaryComparison.
    def visitUnaryComparison(self, ctx:PolicyParser.UnaryComparisonContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#comparison.
    def visitComparison(self, ctx:PolicyParser.ComparisonContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#variable.
    def visitVariable(self, ctx:PolicyParser.VariableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#operator.
    def visitOperator(self, ctx:PolicyParser.OperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#value.
    def visitValue(self, ctx:PolicyParser.ValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#valueList.
    def visitValueList(self, ctx:PolicyParser.ValueListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#listElement.
    def visitListElement(self, ctx:PolicyParser.ListElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#timeWindow.
    def visitTimeWindow(self, ctx:PolicyParser.TimeWindowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#comparisonList.
    def visitComparisonList(self, ctx:PolicyParser.ComparisonListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#logicalCombine.
    def visitLogicalCombine(self, ctx:PolicyParser.LogicalCombineContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by PolicyParser#patternMatch.
    def visitPatternMatch(self, ctx:PolicyParser.PatternMatchContext):
        return self.visitChildren(ctx)



del PolicyParser
