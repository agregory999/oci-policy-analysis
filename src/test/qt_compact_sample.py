"""Synthetic snapshot for exploring the Qt interface without OCI credentials."""


def sample_snapshot() -> dict:
    """Return a fresh version-2 snapshot with clearly fictional policy evidence.

    Returns:
        dict: Small synthetic inventory; group membership is intentionally absent.
    """
    policies = []
    statements = []
    examples = [
        ('Platform visibility', 'Platform', 'Observers', 'inspect', 'all-resources', ''),
        ('Application storage', 'Applications', 'AppDevelopers', 'read', 'objects', ''),
        ('Application storage', 'Applications', 'AppWorkers', 'manage', 'buckets', ''),
        ('Network operations', 'Platform', 'NetworkWorkers', 'manage', 'virtual-network-family', ''),
        ('Audit evidence', 'Security', 'Auditors', 'read', 'audit-events', ''),
        (
            'Restricted secrets',
            'Security',
            'SecurityOperators',
            'read',
            'secret-bundles',
            " where request.networkSource.name = 'corporate-network'",
        ),
    ]
    for index, (name, compartment, group, verb, resource, condition) in enumerate(examples):
        policy_id = 'sample-policy-' + name.lower().replace(' ', '-')
        if not any(item['policy_ocid'] == policy_id for item in policies):
            policies.append(
                {
                    'policy_ocid': policy_id,
                    'policy_name': name,
                    'compartment_ocid': 'sample-' + compartment,
                    'compartment_path': 'ROOT/' + compartment,
                }
            )
        subject_type = 'dynamic-group' if group in {'AppWorkers', 'NetworkWorkers'} else 'group'
        statements.append(
            {
                'internal_id': f'sample-statement-{index}',
                'policy_ocid': policy_id,
                'policy_name': name,
                'compartment_ocid': 'sample-' + compartment,
                'compartment_path': 'ROOT/' + compartment,
                'statement_text': f'Allow {subject_type} {group} to {verb} {resource} in compartment {compartment}{condition}',
                'subject_type': subject_type,
                'subject': [['Default', group]],
                'action': 'allow',
                'valid': True,
                'verb': verb,
                'resource': resource,
                'location_type': 'compartment',
                'location': compartment,
                'conditions': condition.removeprefix(' where '),
            }
        )
    return {
        'version': 2,
        'schema_version': 3,
        'tenancy_name': 'Sample workspace',
        'tenancy_ocid': 'sample-tenancy',
        'snapshot_kind': 'synthetic-demo',
        'inventory_complete': False,
        'data_as_of': 'Synthetic sample — no OCI collection',
        'policies': policies,
        'policy_statements': statements,
        'groups': [
            {'group_name': name, 'domain_name': 'Default', 'id': 'sample-group-' + name}
            for name in sorted({entry[2] for entry in examples} - {'AppWorkers', 'NetworkWorkers'})
        ],
        'dynamic_groups': [
            {
                'domain_name': domain,
                'dynamic_group_name': name,
                'dynamic_group_ocid': ocid,
                'matching_rule': rule,
                'description': 'Fictional sample dynamic group',
            }
            for domain, name, ocid, rule in [
                ('Default', 'AppWorkers', 'sample-dg-app', "ALL {resource.type = 'fnfunc'}"),
                ('Default', 'NetworkWorkers', 'sample-dg-network', "ALL {instance.compartment.id = 'sample-Platform'}"),
                ('Operations', 'AppWorkers', 'sample-dg-other-app', "ALL {resource.type = 'instance'}"),
            ]
        ],
        'compartments': [
            {'id': 'sample-' + name, 'name': name, 'hierarchy_path': 'ROOT/' + name}
            for name in ('Platform', 'Applications', 'Security')
        ],
    }
