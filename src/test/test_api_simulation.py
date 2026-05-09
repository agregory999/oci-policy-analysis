"""
Tests the PolicySimulationEngine API using a predefined compartment path, principal type, and principal.
Replicates the MCP canonical simulation flow, printing the list of where-clause required fields and simulation results.
Assumes all statements are applicable for the selected context.

Run directly as a script for quick testing/development.

Author: Cline AI
"""

from oci_policy_analysis.application.core.engine.policy_simulation_engine import PolicySimulationEngine

# --- Minimal dummy policy and ref data for testing ---


class DummyPolicyRepo:
    def __init__(self):
        self.regular_statements = [
            {
                'internal_id': 'stmt-001',
                'statement_text': "Allow group Admins to inspect buckets in compartment Finance where user.department = 'Finance'",
                'conditions': {'where_clause': "user.department = 'Finance'"},
                'action': 'allow',
                'resource': 'buckets',
                'verb': 'inspect',
                'permission': ['inspect_buckets'],
                'subject_type': 'group',
                'subject': [('Default', 'Admins')],
                'effective_path': 'ROOT/Finance',
            },
            {
                'internal_id': 'stmt-002',
                'statement_text': 'Allow user anita to read buckets in compartment Finance',
                'conditions': None,
                'action': 'allow',
                'resource': 'buckets',
                'verb': 'read',
                'permission': ['read_buckets'],
                'subject_type': 'user',
                'subject': [('Default', 'anita')],
                'effective_path': 'ROOT/Finance',
            },
        ]


class DummyRefDataRepo:
    def __init__(self):
        self.data = {'operations': {'oci:ListBuckets': {'permissions': ['INSPECT_BUCKETS', 'READ_BUCKETS']}}}

    def get_permissions(self, resource, verb, action=None):
        # For test, map resource/verb to operation permissions
        if resource == 'buckets':
            perms = []
            if verb in ('inspect', 'list'):
                perms.append('INSPECT_BUCKETS')
            if verb == 'read':
                perms.append('READ_BUCKETS')
            return perms
        return []

    def has_api_operation_permissions(self, api_operation, given_permissions):
        required = set(self.data.get('operations', {}).get(api_operation, {}).get('permissions', []))
        return required.issubset({p.upper() for p in given_permissions})


# --- TEST HARDCODED VALUES (MCP path style) ---


def main():
    policy_repo = DummyPolicyRepo()
    ref_data_repo = DummyRefDataRepo()
    engine = PolicySimulationEngine(policy_repo=policy_repo, ref_data_repo=ref_data_repo)
    engine.build_index()  # Build mapping for statements

    compartment_path = 'ROOT/Finance'
    principal_type = 'user'
    principal = ('Default', 'anita')  # (domain, name)

    print(
        f'Testing context: compartment_path={compartment_path}, principal_type={principal_type}, principal={principal}'
    )

    # Step 1: Print required where-clause input fields for this context (don't set them)
    required_fields = engine.get_required_where_fields_for_context(compartment_path, principal_type, principal)
    print('Required where-clause fields (do not set):', required_fields)

    # Step 2: Find all applicable statements (assume all would be selected for MCP-style test)
    statements = engine.find_applicable_statements_for_context(compartment_path, principal_type, principal)
    checked_statement_ids = [s['internal_id'] for s in statements]

    # Step 3: Run policy simulation (leave where-context empty to test missing field handling)
    api_operation = 'oci:ListBuckets'
    where_context = {}  # do not set any variables

    principal_key = engine.normalize_principal_key(principal_type, principal)
    result = engine.simulate_and_record(
        principal_key,
        compartment_path,
        api_operation,
        where_context,
        checked_statement_ids,
        trace_name=f'{api_operation} | {principal_key}',
        trace=True,
    )

    print('Simulation result:')
    import pprint

    pprint.pprint(result)


if __name__ == '__main__':
    main()
