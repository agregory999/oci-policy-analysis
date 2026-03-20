"""
Comprehensive subject parsing test cases:
| subject_type     | raw_subject                                                           | expected                                                                                        | Notes                                                         |
|------------------|-----------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| group            | Admins                                                                | [("default", "Admins")]                                                                          | Single group, no domain                                       |
| group            | 'HR'/'HRAdmins'                                                       | [("HR", "HRAdmins")]                                                                             | Group with explicit domain                                    |
| group            | Admins,'HR'/'HRAdmins'                                                | [("default", "Admins"), ("HR", "HRAdmins")]                                                      | Multi group, mix of default and explicit domain               |
| group            | id ocid1.group.oc1..abcxyz                                            | ["ocid1.group.oc1..abcxyz"]                                                                      | Group OCID, id prefix                                         |
| dynamic-group    | 'Federated'/'DXGroup'                                                 | [("Federated", "DXGroup")]                                                                       | Dynamic group with explicit domain                            |
| dynamic-group    | id ocid1.dynamicgroup.oc1..abcxyz, 'Cloud'/'Engineers'                | ["ocid1.dynamicgroup.oc1..abcxyz", ("Cloud", "Engineers")]                                       | Mix of OCID and domain/name for dynamic-group                 |
| service          | 'APIGW' , 'Functions'                                                 | ["APIGW", "Functions"]                                                                           | Multiple services, with spaces and quotes                     |
| any-user         | (empty)                                                               | ["any-user"]                                                                                     | Matches any user type                                         |
| resource         | bucket,foo                                                            | ["bucket", "foo"]                                                                                | Resource subjects, multi-value                                |
| user             | userbob                                                               | ["userbob"]                                                                                      | Fallback type, unknown/unsupported subject_type               |
| (blank)          | miscsubject                                                           | ["miscsubject"]                                                                                  | Fallback blank type, literal subject                          |
| group            | 'OCIDDomain'/'id ocid1.group.oc1..zzzz', id ocid1.group.oc1..yyyy     | [("OCIDDomain", "id ocid1.group.oc1..zzzz"), "ocid1.group.oc1..yyyy"]                            | Edge: quoted OCID as group name, mixed with id-prefixed ocid  |
| (add more rows as real-world tricky/ambiguous examples emerge)                           |                                                                                                  | To ensure coverage                                            |

- All outputs must be canonical: no type prefix ("group", etc) in the final subject list.
- Edge cases: blank input, extra whitespace/quotes, mixed valid names & ocids, ambiguous real OCI patterns.

Expand and maintain this table as new policy subject forms are found in the wild.
"""

import pytest
from oci_policy_analysis.logic.policy_subject_parser import parse_policy_subjects


@pytest.mark.parametrize(
    'subject_type, raw_subject, expected',
    [
        # Groups, single and multiple, default domain and explicit
        ('group', 'Admins', [('default', 'Admins')]),
        ('group', "'HR'/'HRAdmins'", [('HR', 'HRAdmins')]),
        ('group', 'HR/HRAdmins', [('HR', 'HRAdmins')]),
        ('group', "Admins,'HR'/'HRAdmins'", [('default', 'Admins'), ('HR', 'HRAdmins')]),
        ('group', "'DevOps'/'Ci', 'ProdOps'/'Deployers'", [('DevOps', 'Ci'), ('ProdOps', 'Deployers')]),
        # Groups OCID
        (
            'group',
            'id ocid1.group.oc1..aaaaaaaaho65bkmxddua3semo4vkccpqd77hd4itrecoi6z67qmhuz5pggyq',
            ['ocid1.group.oc1..aaaaaaaaho65bkmxddua3semo4vkccpqd77hd4itrecoi6z67qmhuz5pggyq'],
        ),
        # Dynamic group name/OCID
        ('dynamic-group', 'DynamicDataEng', [('default', 'DynamicDataEng')]),
        ('dynamic-group', "'Federated'/'DXGroup'", [('Federated', 'DXGroup')]),
        ('dynamic-group', 'id ocid1.dynamicgroup.oc1..abcxyz', ['ocid1.dynamicgroup.oc1..abcxyz']),
        # Mixed ID/name
        (
            'dynamic-group',
            "id ocid1.dynamicgroup.oc1..abcxyz, 'Cloud'/'Engineers'",
            ['ocid1.dynamicgroup.oc1..abcxyz', ('Cloud', 'Engineers')],
        ),
        # Service, single and multiple
        ('service', 'GenAI', ['GenAI']),
        ('service', 'GenAI,MySQL', ['GenAI', 'MySQL']),
        ('service', " 'APIGW' , 'Functions' ", ['APIGW', 'Functions']),
        # Any-user and any-group
        ('any-user', '', ['any-user']),
        ('any-group', '', ['any-group']),
        # Resource
        ('resource', 'bucket', ['bucket']),
        ('resource', 'bucket,foo', ['bucket', 'foo']),
        # Fallback pattern
        ('user', 'someuser', ['someuser']),
        ('', 'miscsubject', ['miscsubject']),
    ],
)
def test_parse_policy_subjects(subject_type, raw_subject, expected):
    result = parse_policy_subjects(subject_type, raw_subject)
    assert result == expected, f'For {subject_type=}, {raw_subject=}: got {result}, expected {expected}'
