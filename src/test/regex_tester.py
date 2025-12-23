import re

# Updated policy regex with fixed condition+comment handling
POLICY_REGEX = r"""^\s*(?P<action>allow|deny)\s+ # Start with allow or deny action (and whitespace at front)
    (?P<subjecttype>service|any-user|any-group|dynamic-group|group|resource)\s* # Subject type
    (?P<subject>([\w\/\'\.\\, +-]|,)+?)?\s+(to\s+)? # Subject (optional, can be empty in case of any-user)
    ((?P<verb>read|inspect|use|manage)\s+(?P<resource>[\w-]+)|(?P<perm>{[\s*\w\s*|\s*\w\s*,\s*]+}))\s+ # verb and resource or permission set
    in\s+(?P<locationtype>any-tenancy|tenancy|compartment\s+id|compartment)\s* # Location type
    (?P<location>[\w\':.-]+)?(?:\s+where\s+ # Location
    (?P<condition>.+?)(?=(\s*\/\/|$)))? # Condition (optional, non-greedy, stops before // or EOL)
    (?:(?P<optional>\s*\/\/.+))?$ # Comment (optional)
"""
policy_regex = re.compile(POLICY_REGEX, re.IGNORECASE | re.MULTILINE | re.VERBOSE | re.DOTALL)

EXAMPLES = [
    # Simple
    'allow group admins to manage users in tenancy',
    # With where, no comment
    "allow group admins to manage users in tenancy where user.email = '*.acme.com'",
    # With trailing comment
    'allow group admins to manage users in tenancy // this is a comment',
    # Where and trailing comment
    "allow group admins to manage users in tenancy where user.email = '*.acme.com' // match company emails",
    # Multiline with where and comment (newlines inside or after)
    """allow group admins to
manage users
in tenancy where
user.email = '*.acme.com'
// email check""",
    # Where with // in the middle (should split)
    'allow any-user to use resource in tenancy where requestHeader[//bar]=baz // real comment',
    # Where with // inside the string literal
    "allow group analysts to use report in tenancy where report.name = '/usr/logs//foo/bar.log' // comment outer",
    # No condition, just comment
    'allow service api-gateway to inspect api-gateway in any-tenancy // high-level permissions',
    # Complex location and where and comment
    "allow dynamic-group compute-dgs to manage instance-family in compartment id ocid1.compartment.oc1..aaaaaaaabbbbb where instance.launchMode = 'PARAVIRTUALIZED' // legacy mode",
    # Exotic where, multiline
    """allow dynamic-group backup-dgs to use volume-backups in compartment id ocid1.compartment.fake where
request.time > '2024-01-01T00:00:00Z' // scheduled only
""",
    # Only comment
    'allow group admins to manage users in tenancy // admins can manage users',
    # Where contains comment string
    "allow group auditors to use instances in tenancy where note = 'See //auditor docs' // real comment",
    # With permission set, no comment
    'allow group ops to {inspect, read} in tenancy',
    # With permission set and where+comment
    "allow group ops to {inspect, read} in tenancy where op.note != '' // must annotate",
    # Weird whitespace, tabs, etc.
    '  allow any-user     to   manage  bucket   in  compartment data  ',
    # With missing subject (should parse)
    'allow any-user to manage vaults in tenancy',
    # All fields populated
    'deny dynamic-group x to use volume in compartment id ocid1.compartment.real where op=1 // not allowed',
    # Where with numbers and punctuation
    "allow group test to read resource in tenancy where x.y_z '1234.56-78:9' // num",
    # With quoted subject and complex comment
    "allow group 'foo bar' to manage database in tenancy // note: 12, xyz",
    # No comment, but tricky // in string
    "allow group loggers to manage logs in tenancy where log.name = 'prod//logs'",
]

for i, example in enumerate(EXAMPLES, 1):
    m = policy_regex.match(example.strip())
    print(f'\n----- EXAMPLE #{i} -----\n{example.strip()}')
    if m:
        groups = m.groupdict()
        print('  action:    ', repr(groups.get('action')))
        print('  subjecttype:', repr(groups.get('subjecttype')))
        print('  subject:   ', repr(groups.get('subject')))
        print('  verb:      ', repr(groups.get('verb')))
        print('  resource:  ', repr(groups.get('resource')))
        print('  permission:', repr(groups.get('perm')))
        print('  locationt: ', repr(groups.get('locationtype')))
        print('  location:  ', repr(groups.get('location')))
        print('  condition: ', repr(groups.get('condition')))
        print('  comment:   ', repr(groups.get('optional')))
    else:
        print('  >> No match <<')
