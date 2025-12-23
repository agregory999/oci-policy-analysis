import unittest

from oci_policy_analysis.logic.policy_statement_normalizer import PolicyStatementParser


class TestPolicyParser(unittest.TestCase):
    def test_policy_parsing_examples(self):
        # Add policy statements for testing here (one or more per policy block)
        policy_statements = [
            'allow group Admins to manage instances in tenancy',
            'deny group Blocked to read all-resources in tenancy',
            "deny dynamic-group MyDG to use object-family in compartment Foo where request.user.id = 'xyz'",
            "admit group non-default/sales to read buckets in tenancy where request.network.source = '0.0.0.0/0'",
            'endorse dynamic-group DGS to associate instance in any-tenancy',
            'define group G1 as ocid1.xx.yy.zzz',
            "define group 'svcops' as ocid1.xx.yy.zzz",
            'define tenancy t1 as ocid1.tenancy.yy.zzz',
            'deny admit dynamic-group DG1 of tenancy Foo to use buckets in tenancy',
            'deny endorse group G1 to read all-resources in tenancy Bar',
            'endorse group DatabaseToolsConnectionManagers to associate database-tools-connections in tenancy ConnectionTenancy with database-tools-private-endpoints in tenancy PrivateEndpointTenancy',
            'deny endorse group DatabaseToolsConnectionManagers to associate database-tools-connections in tenancy ConnectionTenancy with database-tools-private-endpoints in tenancy PrivateEndpointTenancy',
        ]
        parser = PolicyStatementParser()

        for idx, stmt in enumerate(policy_statements):
            print(f'\nInput statement {idx+1}: {stmt}')
            parsed = parser.parse(stmt)
            if not parsed:
                print('Parsed fields: (none/parse error)')
                continue
            for i, st_dict in enumerate(parsed):
                print(f'Statement {i+1} fields:')
                for k, v in st_dict.items():
                    print(f'  {k}: {v}')


if __name__ == '__main__':
    unittest.main()
