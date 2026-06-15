"""
OCI Policy Subject Parsing Utility

Centralizes all parsing of subject logic (group, dynamic-group, service, resource, any-user, any-group)
for both regular/policy and cross-tenancy statements.

- Input: subject_type (str), raw_subject (str)
- Output: canonical list of tuples/strings as required by normalization

Author: Plan-based refactor by Cline (2026)
"""

import re

from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(component='policy_parser')


def parse_policy_subjects(subject_type: str, raw_subject: str):  # noqa: C901
    """
    Parse the raw subject string from ANTLR into canonical representations used in normalization.

    Returns:
        - Group / dynamic-group: list of tuples (domain, name), or OCID strings
        - Service: list of strings
        - Any-user / any-group: list with single special string
        - Resource: list of resource names or OCIDs (pass-through)
        - group-id/dynamic-group-id: list of tuples (None, OCID)
    """
    subject_type = (subject_type or '').strip().lower()
    raw_subject = (raw_subject or '').strip()
    result = []

    logger.info(f'[parse_policy_subjects] subject_type={subject_type!r}, raw_subject={raw_subject!r}')

    if subject_type in ('any-user', 'any-group'):
        return [subject_type]
    elif subject_type in ('service',):
        # Comma separated, no tuple, no quotes, e.g. 'service A,B'
        items = [i.strip(' \'"') for i in raw_subject.split(',') if i.strip()]
        logger.info(f'[parse_policy_subjects] parsed service subject: {items}')
        return items

    elif subject_type in ('group', 'dynamic-group'):
        # Handle comma-separated names/OCIDs/domain-name pairs.
        # Ex: "'Domain1'/'GroupA',id ocid1..., 'SomeGroup', B/C"
        items = [i.strip() for i in re.split(r',\s*', raw_subject) if i.strip()]
        if not items:
            logger.info('  [psubj] No valid group/dynamic-group subjects extracted from blank/empty input.')
            return []
        for item in items:
            # OCID detection
            if re.match(r'^(id\s+)?ocid1\.', item, re.IGNORECASE):
                m = re.search(r'(ocid1\.[\w\-\.]+)', item, re.IGNORECASE)
                if m:
                    parsed = m.group(1)
                    result.append(parsed)
                    logger.info(f'  [psubj] Detected OCID: {parsed}')
                    continue
            # Domain/name
            if '/' in item:
                left, right = item.split('/', 1)
                domain = left.strip(' \'"')
                name = right.strip(' \'"')
                tup = (domain, name)
                result.append(tup)
                logger.info(f'  [psubj] Detected domain/name: {tup}')
                continue
            # Fallback: just a name, treat as default domain
            parsed = item.strip(' \'"')
            tup = ('default', parsed)
            result.append(tup)
            logger.info(f'  [psubj] Detected default domain: {tup}')
        logger.info(f'[psubj] Canonical normalized group/dynamic-group subjects: {result!r}')
        return result

    elif subject_type in ('group-id', 'dynamic-group-id'):
        # Always return list of (None, OCID) tuples for each OCID (comma-separated)
        items = [i.strip() for i in re.split(r',\s*', raw_subject) if i.strip()]
        ocid_tuples = []
        for item in items:
            # Should not have "id" left, but be tolerant
            m = re.search(r'(ocid1\.[\w\-\.]+)', item, re.IGNORECASE)
            if m:
                ocid = m.group(1)
                tup = (None, ocid)
                ocid_tuples.append(tup)
                logger.info(f'[psubj] Detected OCID (tuple): {tup}')
            else:
                # fallback for any leftovers, return as string (exceptional, for logging)
                logger.info(f'[psubj] Unexpected non-OCID in group-id/dynamic-group-id: {item}')
                ocid_tuples.append((None, item))
        logger.info(f'[psubj] Canonical normalized group/dynamic-group id subjects as tuples: {ocid_tuples!r}')
        return ocid_tuples

    elif subject_type == 'resource':
        # As per resourceSubject, often a single name or OCID in raw_subject.
        items = [i.strip(' \'"') for i in re.split(r',\s*', raw_subject) if i.strip()]
        logger.info(f'[parse_policy_subjects] resource subject: {items}')
        return items

    else:
        # Fallback: log and return string as single element in a list
        logger.info(f'[parse_policy_subjects] Fallback subject: {raw_subject!r}')
        return [raw_subject]
