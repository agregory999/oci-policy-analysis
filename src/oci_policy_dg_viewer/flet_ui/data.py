import oci
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.identity import IdentityClient
from oci.identity_domains import IdentityDomainsClient
from utils import logger


class OCIDataService:
    def __init__(self, config_file='~/.oci/config', profile='DEFAULT', auth_mode='profile'):
        try:
            self.config = None
            self.identity_client = None
            self.domain_clients = {}
            self.domains = {}
            self.compartment_id = None
            self.auth_mode = auth_mode  # Store auth_mode
            self.signer = None  # Store signer for instance principal

            if auth_mode == 'instance_principal':
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.identity_client = IdentityClient(config={}, signer=self.signer)
                self.compartment_id = self.signer.tenancy_id
            else:
                self.config = oci.config.from_file(config_file, profile)
                self.identity_client = IdentityClient(self.config)
                self.compartment_id = self.config['tenancy']

            # List domains using IdentityClient
            domains_response = self.identity_client.list_domains(compartment_id=self.compartment_id)
            if domains_response.data:
                logger.info(f'Found {len(domains_response.data)} identity domains')
                self.domains = {domain.id: domain.display_name for domain in domains_response.data}
                for domain in domains_response.data:
                    logger.debug(f'Domain: {domain.display_name}, URL: {domain.url}')
                    logger.debug(f'Getting IdentityDomainsClient for: {domain} with auth_mode: {auth_mode}')
                    if auth_mode == 'instance_principal':
                        domain_client = IdentityDomainsClient(
                            config={}, signer=self.signer, service_endpoint=domain.url
                        )
                    else:
                        domain_client = IdentityDomainsClient(config=self.config, service_endpoint=domain.url)
                    self.domain_clients[domain.id] = domain_client
            else:
                logger.warning('No identity domains found or access denied')

            logger.info('Identity Domains clients initialized')
        except Exception as e:
            logger.error(f'Failed to initialize Identity Domains clients: {e}')
            raise

    def list_policies(self, compartment_id):
        """List policies using IdentityClient, returning full Policy objects."""
        try:
            policies_response = self.identity_client.list_policies(compartment_id=compartment_id, limit=1000)
            if policies_response.data:
                return [p for p in policies_response.data if p.lifecycle_state == 'ACTIVE']
            logger.warning(f'No policies found for compartment {compartment_id}')
            return []
        except Exception as e:
            logger.error(f'Error listing policies: {e}')
            return []

    def list_users(self):
        """List users across all identity domains with pagination."""
        users = []
        for domain_id, client in self.domain_clients.items():
            try:
                response = client.list_users(
                    attribute_sets=['all'], start_index=1, count=1000, sort_by='displayName', sort_order='ASCENDING'
                )
                if response.data and response.data.resources:
                    users.extend(
                        [
                            {'name': u.display_name, 'id': u.id, 'domain_name': self.domains.get(domain_id, 'Unknown')}
                            for u in response.data.resources
                        ]
                    )
            except Exception as e:
                logger.error(f'Error listing users in domain {domain_id}: {e}')
        return users

    def list_groups(self):
        """List groups across all identity domains with pagination."""
        groups = []
        for domain_id, client in self.domain_clients.items():
            try:
                response = client.list_groups(
                    attribute_sets=['all'], start_index=1, count=1000, sort_by='displayName', sort_order='ASCENDING'
                )
                if response.data and response.data.resources:
                    groups.extend(
                        [
                            {'name': g.display_name, 'id': g.id, 'domain_name': self.domains.get(domain_id, 'Unknown')}
                            for g in response.data.resources
                        ]
                    )
            except Exception as e:
                logger.error(f'Error listing groups in domain {domain_id}: {e}')
        return groups

    def list_dynamic_groups(self):
        """List dynamic groups across all identity domains with pagination."""
        dynamic_groups = []
        for domain_id, client in self.domain_clients.items():
            try:
                response = client.list_dynamic_resource_groups(
                    attribute_sets=['all'], start_index=1, count=1000, sort_by='displayName', sort_order='ASCENDING'
                )
                if response.data and response.data.resources:
                    dynamic_groups.extend(
                        [
                            {
                                'name': dg.display_name,
                                'id': dg.id,
                                'matching_rule': dg.matching_rule,
                                'domain_name': self.domains.get(domain_id, 'Unknown'),
                            }
                            for dg in response.data.resources
                        ]
                    )
            except Exception as e:
                logger.error(f'Error listing dynamic groups in domain {domain_id}: {e}')
        return dynamic_groups
