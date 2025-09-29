import json
from datetime import UTC, datetime
from pathlib import Path

from oci.identity.models import Domain

from logic.data_repo import IdentityDomainsAnalysis, PolicyCompartmentAnalysis
from logic.logger import get_logger

logger = get_logger()

# Cache Directory and Date (for consistency across classes)
CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'
CACHE_DATE = datetime.now(UTC).strftime('%Y-%m-%d-%H-%M-%S-%Z')


# Utility functions for loading and saving cache, using combined caching strategy
def save_combined_cache(
    policy_analysis: PolicyCompartmentAnalysis, domains_analysis: IdentityDomainsAnalysis, export_file=None
) -> str:
    """Save combined cache for policies and dynamic groups. Returns file name if you care"""

    # Create the file as JSON first, collecting all details
    combined_data = {
        'tenancy_name': policy_analysis.tenancy_name,
        'tenancy_ocid': policy_analysis.tenancy_ocid,
        'policies': policy_analysis.regular_statements,
        'dynamic_groups': domains_analysis.dynamic_groups,
        'defined_aliases': policy_analysis.defined_aliases,
        'cross_tenancy_policies': policy_analysis.cross_tenancy_statements,
        'compartments': policy_analysis.compartments,
        'identity_domains': domains_analysis._get_domains(),
        'groups': domains_analysis.groups,
        'users': domains_analysis.users,
        'data_as_of': policy_analysis.data_as_of,
    }

    if export_file:
        with open(export_file.name, 'w', newline='', encoding='utf-8') as filehandle:
            json.dump(combined_data, filehandle, ensure_ascii=False)
        logger.info(f'Exported combined cache to: {export_file.name}')
        return str(export_file.name)

    else:
        # Just write to cache as normal
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        combined_cache_file = CACHE_DIR / f'combined_cache_{policy_analysis.tenancy_name}_{CACHE_DATE}.json'

        with open(combined_cache_file, 'w', encoding='utf-8') as filehandle:
            json.dump(combined_data, filehandle, ensure_ascii=False)
        logger.info(f'Saved combined cache to: {combined_cache_file}')

    # Update cache entries
    entry = {'tenancy_name': policy_analysis.tenancy_name, 'cache_date': CACHE_DATE}
    with open(CACHE_DIR / 'cache_entries.json', 'a', encoding='utf-8') as date_file:
        json.dump(entry, date_file, ensure_ascii=False)
        date_file.write('\n')  # Write a newline after each entry
    logger.info(f'Updated cache entries with: {entry}')

    # Return the name of the file
    return str(combined_cache_file)


def load_cache_from_json(
    loaded_json: dict,
    policy_analysis: PolicyCompartmentAnalysis,
    domains_analysis: IdentityDomainsAnalysis,
) -> bool:
    # Load everything
    logger.info(f'Loaded JSON({type(loaded_json)})')
    try:
        # Grab all of the elements of the cache
        policies = loaded_json.get('policies', [])
        dynamic_groups = loaded_json.get('dynamic_groups', [])
        cross_tenancy_data = loaded_json.get('cross_tenancy_policies', [])
        defined_aliases = loaded_json.get('defined_aliases', [])

        # Set the data in the policy analysis object
        policy_analysis.tenancy_name = loaded_json.get('tenancy_name', '')
        policy_analysis.tenancy_ocid = loaded_json.get('tenancy_ocid', '')
        policy_analysis.compartments = loaded_json.get('compartments', [])
        policy_analysis.regular_statements = policies
        policy_analysis.defined_aliases = defined_aliases
        policy_analysis.cross_tenancy_statements = cross_tenancy_data
        # Set the data in the domains analysis object
        domains_analysis.dynamic_groups = dynamic_groups
        domains_analysis.identity_domains = [
            Domain(id=d['id'], display_name=d['display_name'], url=d['url'])
            for d in loaded_json.get('identity_domains', [])
        ]
        domains_analysis.groups = loaded_json.get('groups', {})
        domains_analysis.users = loaded_json.get('users', {})
        # Set the data as of time
        policy_analysis.data_as_of = loaded_json.get('data_as_of')
        domains_analysis.data_as_of = loaded_json.get('data_as_of')
        logger.info('Loaded combined cache from JSON')
        # Show counts of each loaded element
        logger.info(
            f'Loaded {len(policies)} policies, {len(dynamic_groups)} dynamic groups, '
            f'{len(cross_tenancy_data)} cross-tenancy policies, '
            f'{len(domains_analysis.identity_domains)} identity domains, '
            f'{len(domains_analysis.groups)} groups, and {len(domains_analysis.users)} users from cache.'
        )
        return True
    except json.JSONDecodeError as e:
        logger.error(f'Error decoding JSON from combined cache file: {e}')
        return False
    except Exception as e:
        logger.error(f'Error loading combined cache file: {e}')
        return False


def load_combined_cache(
    named_cache: str,
    policy_analysis: PolicyCompartmentAnalysis,
    domains_analysis: IdentityDomainsAnalysis,
) -> str:
    """Load combined cache for policies and dynamic groups.

    Given the name and data of a cache, loads the data into both of the centralized structures
    for Compartment/Policy and Identity Domain storage.

    Args:
        cached_tenancy: The name of the tenancy to load
        cached_date: The date string of the cache
        policy_analysis: The initialized PolicyCompartmentAnalysis class instance to use
        domains_analysis: The initialized IdentityDomainsAnalysis class instance to use
    Returns:
        A string indicating the name of the file used
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    combined_cache_file = CACHE_DIR / f'combined_cache_{named_cache}.json'
    if combined_cache_file.exists():
        try:
            with open(combined_cache_file, encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                # Grab all of the elements of the cache
                policies = cache_data.get('policies', [])
                dynamic_groups = cache_data.get('dynamic_groups', [])
                cross_tenancy_data = cache_data.get('cross_tenancy_policies', [])
                defined_aliases = cache_data.get('defined_aliases', [])
                # Set the data in the policy analysis object
                policy_analysis.tenancy_name = cache_data.get('tenancy_name', '')
                policy_analysis.tenancy_ocid = cache_data.get('tenancy_ocid', '')
                policy_analysis.compartments = cache_data.get('compartments', [])
                policy_analysis.regular_statements = policies
                policy_analysis.defined_aliases = defined_aliases
                policy_analysis.cross_tenancy_statements = cross_tenancy_data
                # Set the data in the domains analysis object
                domains_analysis.dynamic_groups = dynamic_groups
                domains_analysis.identity_domains = [
                    Domain(id=d['id'], display_name=d['display_name'], url=d['url'])
                    for d in cache_data.get('identity_domains', [])
                ]
                domains_analysis.groups = cache_data.get('groups', {})
                domains_analysis.users = cache_data.get('users', {})
                # Set the data as of time
                policy_analysis.data_as_of = cache_data.get('data_as_of')
                domains_analysis.data_as_of = cache_data.get('data_as_of')
                logger.info(f'Loaded combined cache from: {combined_cache_file}')
                # Show counts of each loaded element
                logger.info(
                    f'Loaded {len(policies)} policies, {len(dynamic_groups)} dynamic groups, '
                    f'{len(cross_tenancy_data)} cross-tenancy policies, '
                    f'{len(domains_analysis.identity_domains)} identity domains, '
                    f'{len(domains_analysis.groups)} groups, and {len(domains_analysis.users)} users from cache.'
                )

        except json.JSONDecodeError as e:
            logger.error(f'Error decoding JSON from combined cache file: {e}')
            return 'no cache'
        except Exception as e:
            logger.error(f'Error loading combined cache file: {e}')
            return 'no cache'
    logger.warning(f'Unable to load data from cache: {combined_cache_file}')
    return str(combined_cache_file)


def get_available_cache(tenancy_name: str | None) -> list[str]:
    """Get available cache files for a given profile

    If given no argument, simply return the list of all avialable cache files that
    exist in the cache directory.  Entries will contain the tenancy name and date loaded.

    Args:
        tenancy_name: The name of an OCI tenancy, which will filter the cache list down to only
        caches for that tenancy.

    Returns:
        a list of the available named caches
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return_entries = []
    try:
        with open(CACHE_DIR / 'cache_entries.json', encoding='utf-8') as date_file:
            entries = date_file.readlines()
        logger.debug(f'Entries found in cache_entries.json: {entries}')
        entries.reverse()  # Show most recent first
        logger.debug(f'Entries found in cache_entries.json (Reversed): {entries}')

        for entry in entries:
            cache = json.loads(entry)
            if tenancy_name and cache['tenancy_name'] != tenancy_name:
                continue
            return_entries.append(cache['tenancy_name'] + '\n' + cache['cache_date'])
    except json.JSONDecodeError:
        logger.warning('No cache entries found or cache_entries.json is empty.')
    except FileNotFoundError:
        logger.warning('cache_entries.json file not found. No cache entries available.')

    logger.info(f'Entries found in cache_entries.json: {len(return_entries)}')
    return return_entries


def load_cache_into_local_json(
    cached_tenancy: str,
    cached_date: str,
) -> dict:
    # Load everything into a JSON dict and return it
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    combined_cache_file = CACHE_DIR / f'combined_cache_{cached_tenancy}_{cached_date}.json'
    if combined_cache_file.exists():
        try:
            with open(combined_cache_file, encoding='utf-8') as filehandle:
                cache_data = json.load(filehandle)
                logger.info(f'Loaded combined cache from: {combined_cache_file}')
                # Show counts of each loaded element
                # Return data as object
                return cache_data
        except json.JSONDecodeError as e:
            logger.error(f'Error decoding JSON from combined cache file: {e}')
            return {}
        except Exception as e:
            logger.error(f'Error loading combined cache file: {e}')
            return {}
    logger.warning(f'Unable to load data from cache: {combined_cache_file}')
    return {}
