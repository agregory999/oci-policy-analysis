grammar Policy;

 /*
  * Parser Rules
  */
 policy              : ( allowExpression | endorseExpression | defineExpression | admitExpression )+  EOF ;

 allowExpression
     : (ALLOW | DENY | DENY ALLOW)
        subject (TO? verb resource | TO? permissionList)
        IN scope (WHERE condition)? (COMMENT)? NEWLINE?
     ;
 endorseExpression
     : (ENDORSE | DENY ENDORSE)
        subject (TO endorseVerb resource | TO? permissionList)
        IN endorseScope
        (WITH resource IN endorseScope)?
        (WHERE condition)? (COMMENT)? NEWLINE?
     ;
 defineExpression
     : DEFINE definedSubject AS defined (COMMENT)? NEWLINE?
     ;
 admitExpression
     : (ADMIT | DENY ADMIT)
        subject (OF endorseScope)?
        (TO endorseVerb resource | TO? permissionList)
        IN scope
        (WITH resource IN endorseScope)?
        (WHERE condition)? (COMMENT)? NEWLINE?
     ;

 endorseVerb         : (verb | ASSOCIATE);
 verb                : (INSPECT | READ | USE | MANAGE) ;
 permissionList      : '{'  WORD  (',' WORD)* '}'  ; // e.g {USER_UPDATE, USER_UIPASS_SET, USER_UIPASS_SET}
 scope               : ((COMPARTMENT ID?)  (WORD | HCL_VAR) (':' (WORD | HCL_VAR))* | TENANCY) ;
 endorseScope        : (ANYTENANCY| TENANCY (WORD | HCL_VAR));
 subject             : (groupSubject | serviceSubject | dynamicGroupSubject | resourceSubject | ANYUSER) ;
 groupSubject        : GROUP (groupName| groupID) (','(groupName|groupID))* ;
 resourceSubject     : RESOURCE resourceSubjectId (resourceSubjectId)*;
 serviceSubject      : SERVICE serviceSubjectId (',' serviceSubjectId)*;
 groupName           : (WORD | QUOTED_STRING '/' QUOTED_STRING | QUOTED_STRING | WORD '/' WORD | WORD '/' QUOTED_STRING | HCL_VAR);
 resourceSubjectId   : (WORD | HCL_VAR) ('\'' (WORD | HCL_VAR) '\'' | '\'' (WORD | HCL_VAR) '/' (WORD | HCL_VAR) '\'' )+?;
 serviceSubjectId    : (WORD | HCL_VAR);
 groupID             : ID (WORD | HCL_VAR);
 dynamicGroupSubject : DYNAMICGROUP (groupName| groupID) (','(groupName|groupID))* ;
 tenancySubject      : TENANCY (WORD | HCL_VAR);
 definedSubject      : (groupSubject | dynamicGroupSubject | serviceSubject | tenancySubject);
 defined             : (WORD | HCL_VAR);
 resource            : (WORD | HCL_VAR);
 condition           : (comparisonList | comparison | HCL_VAR) ; // Added HCL_VAR to allow conditions to be HCL variables
 comparison          : variable operator (value|valueList|timeWindow| patternMatch) ;
 variable            : (WORD | HCL_VAR) (('.' (WORD | HCL_VAR) )+)? ;
 operator            : ('=' | '!''=' | BEFORE | IN | BETWEEN) ;
 value               : (WORD 
                     | QUOTED_STRING 
                     | QUOTED_STRING '/' WORD 
                     | QUOTED_STRING (WS WORD)+ 
                     | HCL_VAR
                     | '\'' HCL_VAR '\''  // Add support for quoted variables
                     );
 valueList           : '(' (QUOTED_STRING | HCL_VAR | '\'' HCL_VAR '\'') ( ',' (QUOTED_STRING | HCL_VAR | '\'' HCL_VAR '\'') )*  ')';
 timeWindow          : (QUOTED_STRING | HCL_VAR | '\'' HCL_VAR '\'') AND (QUOTED_STRING | HCL_VAR | '\'' HCL_VAR '\'');

 comparisonList      : logicalCombine '{' condition  (',' condition)* '}' ;
 logicalCombine      : ( ALL | ANY ) ;
 patternMatch        : ('/' WORD '*/'|'/*' WORD '/'| '/' WORD '/'|'/*' WORD '*/') ;

 /*
  * Lexer Rules
  */
 BEFORE              : B E F O R E ;
 BETWEEN             : B E T W E E N;
 NEWLINE             : ('\r'? '\n' | '\r')+ -> skip;
 COMMENT             : '//' ~[\r\n]* ;
 QUOTED_STRING       : '\'' (LETTER | DIGIT | ' ' | '-' | '.' | ':' | '@' | '_' | '/')+ '\'' ;
 WS                  : ' '+  -> skip;
 ANYUSER             : A N Y '-' U S E R  ;
 ANYTENANCY          : A N Y '-' T E N A N C Y ;
 ENDORSE             : E N D O R S E ;
 ALLOW               : A L L O W;
 DENY                : D E N Y;
 DEFINE              : D E F I N E ;
 RESOURCE            : R E S O U R C E ;
 TO                  : T O;
 OF                  : O F ;
 IN                  : I N;
 WHERE               : W H E R E  ;
 WITH                : W I T H ;
 DYNAMICGROUP        : D Y N A M I C '-' G R O U P ;
 GROUP               : G R O U P  ;
 SERVICE             : S E R V I C E  ;
 COMPARTMENT         : C O M P A R T M E N T  ;
 TENANCY             : T E N A N C Y;
 READ                : R E A D  ;
 INSPECT             : I N S P E C T  ;
 MANAGE              : M A N A G E  ;
 ASSOCIATE           : A S S O C I A T E ;
 ADMIT               : A D M I T ;
 USE                 : U S E  ;
 ANY                 : A N Y  ;
 AND                 : A N D;
 ALL                 : A L L  ;
 AS                  : A S;
 ID                  : I D;

 /*
  * HCL (HashiCorp Configuration Language) variable interpolation support
  * Matches ${var.name} syntax used in Terraform files
  * Example: Allow group ${var.admin_group} to manage all-resources in tenancy
  */
 HCL_VAR             : '${' (~[}])+ '}' ;

 // Word is last to prevent ambiguity with other tokens
 WORD                : (LETTER | DIGIT | '_' | '-' | '.' | ':'| '@')+ ;

 fragment LETTER     : [a-zA-Z] ;
 fragment DIGIT      : [0-9] ;
 fragment A          : ('a'|'A') ;
 fragment L          : ('l'|'L') ;
 fragment O          : ('o'|'O') ;
 fragment W          : ('w'|'W') ;
 fragment I          : ('i'|'I') ;
 fragment N          : ('n'|'N') ;
 fragment T          : ('t'|'T') ;
 fragment E          : ('e'|'E') ;
 fragment R          : ('r'|'R') ;
 fragment H          : ('h'|'H') ;
 fragment U          : ('u'|'U') ;
 fragment P          : ('p'|'P') ;
 fragment S          : ('s'|'S') ;
 fragment V          : ('v'|'V') ;
 fragment C          : ('c'|'C') ;
 fragment D          : ('d'|'D') ;
 fragment M          : ('m'|'M') ;
 fragment G          : ('g'|'G') ;
 fragment Y          : ('y'|'Y') ;
 fragment F          : ('f'|'F') ;
 fragment B          : ('b'|'B') ;
