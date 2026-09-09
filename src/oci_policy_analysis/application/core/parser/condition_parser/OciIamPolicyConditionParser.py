# Generated from OciIamPolicyCondition.g4 by ANTLR 4.13.2
import sys

from antlr4 import *

if sys.version_info[1] > 5:
    from typing import TextIO
else:
    from typing.io import TextIO

def serializedATN():
    return [
        4,1,28,76,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,2,6,7,
        6,2,7,7,7,2,8,7,8,1,0,1,0,1,0,1,1,1,1,1,1,1,1,1,1,1,1,3,1,28,8,1,
        1,2,1,2,1,2,5,2,33,8,2,10,2,12,2,36,9,2,1,3,1,3,1,3,1,3,1,3,1,3,
        3,3,44,8,3,1,3,1,3,3,3,48,8,3,3,3,50,8,3,1,4,1,4,1,4,5,4,55,8,4,
        10,4,12,4,58,9,4,1,5,1,5,1,6,1,6,1,6,1,6,1,7,1,7,1,7,5,7,69,8,7,
        10,7,12,7,72,9,7,1,8,1,8,1,8,0,0,9,0,2,4,6,8,10,12,14,16,0,4,1,0,
        4,5,1,0,23,26,1,0,24,26,1,0,1,2,73,0,18,1,0,0,0,2,27,1,0,0,0,4,29,
        1,0,0,0,6,49,1,0,0,0,8,51,1,0,0,0,10,59,1,0,0,0,12,61,1,0,0,0,14,
        65,1,0,0,0,16,73,1,0,0,0,18,19,3,2,1,0,19,20,5,0,0,1,20,1,1,0,0,
        0,21,28,3,6,3,0,22,23,3,16,8,0,23,24,5,19,0,0,24,25,3,4,2,0,25,26,
        5,20,0,0,26,28,1,0,0,0,27,21,1,0,0,0,27,22,1,0,0,0,28,3,1,0,0,0,
        29,34,3,2,1,0,30,31,5,17,0,0,31,33,3,2,1,0,32,30,1,0,0,0,33,36,1,
        0,0,0,34,32,1,0,0,0,34,35,1,0,0,0,35,5,1,0,0,0,36,34,1,0,0,0,37,
        38,5,6,0,0,38,50,3,8,4,0,39,40,3,8,4,0,40,43,7,0,0,0,41,44,3,10,
        5,0,42,44,3,12,6,0,43,41,1,0,0,0,43,42,1,0,0,0,44,47,1,0,0,0,45,
        46,5,3,0,0,46,48,3,10,5,0,47,45,1,0,0,0,47,48,1,0,0,0,48,50,1,0,
        0,0,49,37,1,0,0,0,49,39,1,0,0,0,50,7,1,0,0,0,51,56,5,26,0,0,52,53,
        5,18,0,0,53,55,5,26,0,0,54,52,1,0,0,0,55,58,1,0,0,0,56,54,1,0,0,
        0,56,57,1,0,0,0,57,9,1,0,0,0,58,56,1,0,0,0,59,60,7,1,0,0,60,11,1,
        0,0,0,61,62,5,21,0,0,62,63,3,14,7,0,63,64,5,22,0,0,64,13,1,0,0,0,
        65,70,7,2,0,0,66,67,5,17,0,0,67,69,7,2,0,0,68,66,1,0,0,0,69,72,1,
        0,0,0,70,68,1,0,0,0,70,71,1,0,0,0,71,15,1,0,0,0,72,70,1,0,0,0,73,
        74,7,3,0,0,74,17,1,0,0,0,7,27,34,43,47,49,56,70
    ]

class OciIamPolicyConditionParser ( Parser ):

    grammarFileName = "OciIamPolicyCondition.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>",
                     "<INVALID>", "<INVALID>", "'!'", "'='", "'!='", "'>'",
                     "'<'", "'>='", "'<='", "<INVALID>", "<INVALID>", "<INVALID>",
                     "<INVALID>", "','", "'.'", "'{'", "'}'", "'('", "')'" ]

    symbolicNames = [ "<INVALID>", "ALL", "ANY", "AND", "OPERATOR", "NOT_IN",
                      "BANG", "EQ", "NEQ", "GT", "LT", "GTE", "LTE", "IN_OP",
                      "BEFORE", "AFTER", "BETWEEN", "COMMA", "DOT", "OPEN_CURLY",
                      "CLOSE_CURLY", "OPEN_PAREN", "CLOSE_PAREN", "OCID",
                      "STRING_LITERAL", "PATTERN_LITERAL", "IDENTIFIER",
                      "WHITESPACE", "COMMENT" ]

    RULE_condition_clause = 0
    RULE_condition_expression = 1
    RULE_condition_list = 2
    RULE_single_condition = 3
    RULE_variable_name = 4
    RULE_condition_value = 5
    RULE_literal_list = 6
    RULE_literal_list_content = 7
    RULE_all_or_any = 8

    ruleNames =  [ "condition_clause", "condition_expression", "condition_list",
                   "single_condition", "variable_name", "condition_value",
                   "literal_list", "literal_list_content", "all_or_any" ]

    EOF = Token.EOF
    ALL=1
    ANY=2
    AND=3
    OPERATOR=4
    NOT_IN=5
    BANG=6
    EQ=7
    NEQ=8
    GT=9
    LT=10
    GTE=11
    LTE=12
    IN_OP=13
    BEFORE=14
    AFTER=15
    BETWEEN=16
    COMMA=17
    DOT=18
    OPEN_CURLY=19
    CLOSE_CURLY=20
    OPEN_PAREN=21
    CLOSE_PAREN=22
    OCID=23
    STRING_LITERAL=24
    PATTERN_LITERAL=25
    IDENTIFIER=26
    WHITESPACE=27
    COMMENT=28

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.2")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class Condition_clauseContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def condition_expression(self):
            return self.getTypedRuleContext(OciIamPolicyConditionParser.Condition_expressionContext,0)


        def EOF(self):
            return self.getToken(OciIamPolicyConditionParser.EOF, 0)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_condition_clause

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterCondition_clause" ):
                listener.enterCondition_clause(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitCondition_clause" ):
                listener.exitCondition_clause(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitCondition_clause" ):
                return visitor.visitCondition_clause(self)
            else:
                return visitor.visitChildren(self)




    def condition_clause(self):

        localctx = OciIamPolicyConditionParser.Condition_clauseContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_condition_clause)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 18
            self.condition_expression()
            self.state = 19
            self.match(OciIamPolicyConditionParser.EOF)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Condition_expressionContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def single_condition(self):
            return self.getTypedRuleContext(OciIamPolicyConditionParser.Single_conditionContext,0)


        def all_or_any(self):
            return self.getTypedRuleContext(OciIamPolicyConditionParser.All_or_anyContext,0)


        def OPEN_CURLY(self):
            return self.getToken(OciIamPolicyConditionParser.OPEN_CURLY, 0)

        def condition_list(self):
            return self.getTypedRuleContext(OciIamPolicyConditionParser.Condition_listContext,0)


        def CLOSE_CURLY(self):
            return self.getToken(OciIamPolicyConditionParser.CLOSE_CURLY, 0)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_condition_expression

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterCondition_expression" ):
                listener.enterCondition_expression(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitCondition_expression" ):
                listener.exitCondition_expression(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitCondition_expression" ):
                return visitor.visitCondition_expression(self)
            else:
                return visitor.visitChildren(self)




    def condition_expression(self):

        localctx = OciIamPolicyConditionParser.Condition_expressionContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_condition_expression)
        try:
            self.state = 27
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [6, 26]:
                self.enterOuterAlt(localctx, 1)
                self.state = 21
                self.single_condition()
                pass
            elif token in [1, 2]:
                self.enterOuterAlt(localctx, 2)
                self.state = 22
                self.all_or_any()
                self.state = 23
                self.match(OciIamPolicyConditionParser.OPEN_CURLY)
                self.state = 24
                self.condition_list()
                self.state = 25
                self.match(OciIamPolicyConditionParser.CLOSE_CURLY)
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Condition_listContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def condition_expression(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(OciIamPolicyConditionParser.Condition_expressionContext)
            else:
                return self.getTypedRuleContext(OciIamPolicyConditionParser.Condition_expressionContext,i)


        def COMMA(self, i:int=None):
            if i is None:
                return self.getTokens(OciIamPolicyConditionParser.COMMA)
            else:
                return self.getToken(OciIamPolicyConditionParser.COMMA, i)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_condition_list

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterCondition_list" ):
                listener.enterCondition_list(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitCondition_list" ):
                listener.exitCondition_list(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitCondition_list" ):
                return visitor.visitCondition_list(self)
            else:
                return visitor.visitChildren(self)




    def condition_list(self):

        localctx = OciIamPolicyConditionParser.Condition_listContext(self, self._ctx, self.state)
        self.enterRule(localctx, 4, self.RULE_condition_list)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 29
            self.condition_expression()
            self.state = 34
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==17:
                self.state = 30
                self.match(OciIamPolicyConditionParser.COMMA)
                self.state = 31
                self.condition_expression()
                self.state = 36
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Single_conditionContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def BANG(self):
            return self.getToken(OciIamPolicyConditionParser.BANG, 0)

        def variable_name(self):
            return self.getTypedRuleContext(OciIamPolicyConditionParser.Variable_nameContext,0)


        def NOT_IN(self):
            return self.getToken(OciIamPolicyConditionParser.NOT_IN, 0)

        def OPERATOR(self):
            return self.getToken(OciIamPolicyConditionParser.OPERATOR, 0)

        def condition_value(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(OciIamPolicyConditionParser.Condition_valueContext)
            else:
                return self.getTypedRuleContext(OciIamPolicyConditionParser.Condition_valueContext,i)


        def literal_list(self):
            return self.getTypedRuleContext(OciIamPolicyConditionParser.Literal_listContext,0)


        def AND(self):
            return self.getToken(OciIamPolicyConditionParser.AND, 0)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_single_condition

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterSingle_condition" ):
                listener.enterSingle_condition(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitSingle_condition" ):
                listener.exitSingle_condition(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitSingle_condition" ):
                return visitor.visitSingle_condition(self)
            else:
                return visitor.visitChildren(self)




    def single_condition(self):

        localctx = OciIamPolicyConditionParser.Single_conditionContext(self, self._ctx, self.state)
        self.enterRule(localctx, 6, self.RULE_single_condition)
        self._la = 0 # Token type
        try:
            self.state = 49
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [6]:
                self.enterOuterAlt(localctx, 1)
                self.state = 37
                self.match(OciIamPolicyConditionParser.BANG)
                self.state = 38
                self.variable_name()
                pass
            elif token in [26]:
                self.enterOuterAlt(localctx, 2)
                self.state = 39
                self.variable_name()
                self.state = 40
                _la = self._input.LA(1)
                if not(_la==4 or _la==5):
                    self._errHandler.recoverInline(self)
                else:
                    self._errHandler.reportMatch(self)
                    self.consume()
                self.state = 43
                self._errHandler.sync(self)
                token = self._input.LA(1)
                if token in [23, 24, 25, 26]:
                    self.state = 41
                    self.condition_value()
                    pass
                elif token in [21]:
                    self.state = 42
                    self.literal_list()
                    pass
                else:
                    raise NoViableAltException(self)

                self.state = 47
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if _la==3:
                    self.state = 45
                    self.match(OciIamPolicyConditionParser.AND)
                    self.state = 46
                    self.condition_value()


                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Variable_nameContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def IDENTIFIER(self, i:int=None):
            if i is None:
                return self.getTokens(OciIamPolicyConditionParser.IDENTIFIER)
            else:
                return self.getToken(OciIamPolicyConditionParser.IDENTIFIER, i)

        def DOT(self, i:int=None):
            if i is None:
                return self.getTokens(OciIamPolicyConditionParser.DOT)
            else:
                return self.getToken(OciIamPolicyConditionParser.DOT, i)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_variable_name

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterVariable_name" ):
                listener.enterVariable_name(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitVariable_name" ):
                listener.exitVariable_name(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitVariable_name" ):
                return visitor.visitVariable_name(self)
            else:
                return visitor.visitChildren(self)




    def variable_name(self):

        localctx = OciIamPolicyConditionParser.Variable_nameContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_variable_name)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 51
            self.match(OciIamPolicyConditionParser.IDENTIFIER)
            self.state = 56
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==18:
                self.state = 52
                self.match(OciIamPolicyConditionParser.DOT)
                self.state = 53
                self.match(OciIamPolicyConditionParser.IDENTIFIER)
                self.state = 58
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Condition_valueContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def STRING_LITERAL(self):
            return self.getToken(OciIamPolicyConditionParser.STRING_LITERAL, 0)

        def OCID(self):
            return self.getToken(OciIamPolicyConditionParser.OCID, 0)

        def PATTERN_LITERAL(self):
            return self.getToken(OciIamPolicyConditionParser.PATTERN_LITERAL, 0)

        def IDENTIFIER(self):
            return self.getToken(OciIamPolicyConditionParser.IDENTIFIER, 0)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_condition_value

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterCondition_value" ):
                listener.enterCondition_value(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitCondition_value" ):
                listener.exitCondition_value(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitCondition_value" ):
                return visitor.visitCondition_value(self)
            else:
                return visitor.visitChildren(self)




    def condition_value(self):

        localctx = OciIamPolicyConditionParser.Condition_valueContext(self, self._ctx, self.state)
        self.enterRule(localctx, 10, self.RULE_condition_value)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 59
            _la = self._input.LA(1)
            if not(((_la) & ~0x3f) == 0 and ((1 << _la) & 125829120) != 0):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Literal_listContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def OPEN_PAREN(self):
            return self.getToken(OciIamPolicyConditionParser.OPEN_PAREN, 0)

        def literal_list_content(self):
            return self.getTypedRuleContext(OciIamPolicyConditionParser.Literal_list_contentContext,0)


        def CLOSE_PAREN(self):
            return self.getToken(OciIamPolicyConditionParser.CLOSE_PAREN, 0)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_literal_list

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterLiteral_list" ):
                listener.enterLiteral_list(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitLiteral_list" ):
                listener.exitLiteral_list(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitLiteral_list" ):
                return visitor.visitLiteral_list(self)
            else:
                return visitor.visitChildren(self)




    def literal_list(self):

        localctx = OciIamPolicyConditionParser.Literal_listContext(self, self._ctx, self.state)
        self.enterRule(localctx, 12, self.RULE_literal_list)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 61
            self.match(OciIamPolicyConditionParser.OPEN_PAREN)
            self.state = 62
            self.literal_list_content()
            self.state = 63
            self.match(OciIamPolicyConditionParser.CLOSE_PAREN)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Literal_list_contentContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def STRING_LITERAL(self, i:int=None):
            if i is None:
                return self.getTokens(OciIamPolicyConditionParser.STRING_LITERAL)
            else:
                return self.getToken(OciIamPolicyConditionParser.STRING_LITERAL, i)

        def PATTERN_LITERAL(self, i:int=None):
            if i is None:
                return self.getTokens(OciIamPolicyConditionParser.PATTERN_LITERAL)
            else:
                return self.getToken(OciIamPolicyConditionParser.PATTERN_LITERAL, i)

        def IDENTIFIER(self, i:int=None):
            if i is None:
                return self.getTokens(OciIamPolicyConditionParser.IDENTIFIER)
            else:
                return self.getToken(OciIamPolicyConditionParser.IDENTIFIER, i)

        def COMMA(self, i:int=None):
            if i is None:
                return self.getTokens(OciIamPolicyConditionParser.COMMA)
            else:
                return self.getToken(OciIamPolicyConditionParser.COMMA, i)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_literal_list_content

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterLiteral_list_content" ):
                listener.enterLiteral_list_content(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitLiteral_list_content" ):
                listener.exitLiteral_list_content(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitLiteral_list_content" ):
                return visitor.visitLiteral_list_content(self)
            else:
                return visitor.visitChildren(self)




    def literal_list_content(self):

        localctx = OciIamPolicyConditionParser.Literal_list_contentContext(self, self._ctx, self.state)
        self.enterRule(localctx, 14, self.RULE_literal_list_content)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 65
            _la = self._input.LA(1)
            if not(((_la) & ~0x3f) == 0 and ((1 << _la) & 117440512) != 0):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
            self.state = 70
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==17:
                self.state = 66
                self.match(OciIamPolicyConditionParser.COMMA)
                self.state = 67
                _la = self._input.LA(1)
                if not(((_la) & ~0x3f) == 0 and ((1 << _la) & 117440512) != 0):
                    self._errHandler.recoverInline(self)
                else:
                    self._errHandler.reportMatch(self)
                    self.consume()
                self.state = 72
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class All_or_anyContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def ALL(self):
            return self.getToken(OciIamPolicyConditionParser.ALL, 0)

        def ANY(self):
            return self.getToken(OciIamPolicyConditionParser.ANY, 0)

        def getRuleIndex(self):
            return OciIamPolicyConditionParser.RULE_all_or_any

        def enterRule(self, listener:ParseTreeListener):
            if hasattr( listener, "enterAll_or_any" ):
                listener.enterAll_or_any(self)

        def exitRule(self, listener:ParseTreeListener):
            if hasattr( listener, "exitAll_or_any" ):
                listener.exitAll_or_any(self)

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitAll_or_any" ):
                return visitor.visitAll_or_any(self)
            else:
                return visitor.visitChildren(self)




    def all_or_any(self):

        localctx = OciIamPolicyConditionParser.All_or_anyContext(self, self._ctx, self.state)
        self.enterRule(localctx, 16, self.RULE_all_or_any)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 73
            _la = self._input.LA(1)
            if not(_la==1 or _la==2):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx
