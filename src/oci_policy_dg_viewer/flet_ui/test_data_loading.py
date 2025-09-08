import argparse
import json
import logging

from data import OCIDataService
from utils import logger  # Reuse your logger from utils.py

# Configure logging for the test script
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def test_data_loading(auth_mode='profile', profile='DEFAULT'):
    """Test script to initialize OCIDataService and call load functions."""
    try:
        # Initialize OCIDataService
        data_service = OCIDataService(auth_mode=auth_mode, profile=profile)
        logger.info('OCIDataService initialized successfully')

        # Test list_policies
        # policies = data_service.list_policies(data_service.compartment_id)
        # logger.info(f"Loaded {len(policies)} policies")
        # print("Policies:")
        # print(json.dumps([p.__dict__ for p in policies], default=str, indent=4))

        # Test list_users
        users = data_service.list_users(data_service.compartment_id)
        logger.info(f'Loaded {len(users)} users')
        print('Users:')
        print(json.dumps([u.__dict__ for u in users], default=str, indent=4))

        # # Test list_groups
        # groups = data_service.list_groups(data_service.compartment_id)
        # logger.info(f"Loaded {len(groups)} groups")
        # print("Groups:")
        # print(json.dumps([g.__dict__ for g in groups], default=str, indent=4))

        # # Test list_dynamic_groups
        # dynamic_groups = data_service.list_dynamic_groups(data_service.compartment_id)
        # logger.info(f"Loaded {len(dynamic_groups)} dynamic groups")
        # print("Dynamic Groups:")
        # print(json.dumps([dg.__dict__ for dg in dynamic_groups], default=str, indent=4))

    except Exception as e:
        logger.error(f'Error during data loading test: {e}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test OCI Data Loading')
    parser.add_argument(
        '--auth_mode', default='profile', choices=['profile', 'instance_principal'], help='Authentication mode'
    )
    parser.add_argument('--profile', default='DEFAULT', help='OCI config profile (for profile mode)')
    args = parser.parse_args()

    test_data_loading(auth_mode=args.auth_mode, profile=args.profile)
