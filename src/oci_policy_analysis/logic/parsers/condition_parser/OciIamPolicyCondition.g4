// ANTLR4 Grammar for OCI IAM Policy WHERE Clause

grammar OciIamPolicyCondition;

// --- Parser Rules ---

condition_clause
    : condition_expression EOF
    ;

condition_expression
    : single_condition
    | all_or_any OPEN_CURLY condition_list CLOSE_CURLY
    ;

condition_list
    : condition_expression (COMMA condition_expression)*
    ;

single_condition
    // Handles IN/NOT IN with list, standard operators with single value, AND BETWEEN with two values
    : variable_name (NOT_IN | OPERATOR) (condition_value | literal_list) (AND condition_value)?
    ;

variable_name
    : IDENTIFIER (DOT IDENTIFIER)*
    ;

condition_value
    : STRING_LITERAL
    | OCID
    | PATTERN_LITERAL
    | IDENTIFIER
    ;

literal_list
    : OPEN_PAREN literal_list_content CLOSE_PAREN
    ;

literal_list_content
    : (STRING_LITERAL | PATTERN_LITERAL | IDENTIFIER) (COMMA (STRING_LITERAL | PATTERN_LITERAL | IDENTIFIER))*
    ;

all_or_any
    : ALL
    | ANY
    ;


// --- Lexer Rules (The Vocabulary) ---
// Keywords
ALL             : [Aa][Ll][Ll] ;
ANY             : [Aa][Nn][Yy] ;
AND             : [Aa][Nn][Dd] ; // Added AND keyword for BETWEEN

// Operators
OPERATOR        : EQ | NEQ | GT | LT | GTE | LTE | IN_OP | BEFORE | AFTER | BETWEEN ;
NOT_IN          : [Nn][Oo][Tt] WHITESPACE+ [Ii][Nn] ;
EQ              : '=' ;
NEQ             : '!=' ;
GT              : '>' ;
LT              : '<' ;
GTE             : '>=' ;
LTE             : '<=' ;
IN_OP           : [Ii][Nn] ;
BEFORE          : [Bb][Ee][Ff][Oo][Rr][Ee] ;
AFTER           : [Aa][Ff][Tt][Ee][Rr] ;
BETWEEN         : [Bb][Ee][Tt][Ww][Ee][Ee][Nn] ; // Added

// NOTE: Place IDENTIFIER rule AFTER OPERATOR and KEYWORDS for correct lexer priority!
// ANTLR chooses the first matching rule, so this avoids 'in' being tokenized as part of an identifier.

// Punctuation and Structural Tokens
COMMA           : ',' ;
DOT             : '.' ;
OPEN_CURLY      : '{' ;
CLOSE_CURLY     : '}' ;
OPEN_PAREN      : '(' ;
CLOSE_PAREN     : ')' ;

// Lexemes (Data Types)
OCID            : 'ocid1.' [a-zA-Z0-9.]+ ;

STRING_LITERAL
    : '\'' (~[\r\n'])* '\''
    ;

PATTERN_LITERAL
    : '/' (~[\r\n/])* '/'
    ;

// *** IDENTIFIER rule MUST follow keywords/operators for 'in' parsing bug fix ***
IDENTIFIER
    : [a-zA-Z] [a-zA-Z0-9._-]*
    ;

// White space and comments are ignored
WHITESPACE      : [ \t\r\n]+ -> skip ;
COMMENT         : '#' ~[\r\n]* -> skip;

// After editing this grammar, you must regenerate the lexer/parser with `antlr4 OciIamPolicyCondition.g4` and rebuild!
