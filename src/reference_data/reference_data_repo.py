# reference_data_repo.py

import glob
import json
import os

from oci_policy_analysis.logger import get_logger

logger = get_logger(component='reference_data_repo')


class ReferenceDataRepo:
    def __init__(self, json_dir='permissions'):
        self.json_dir = os.path.join(os.path.dirname(__file__), json_dir)
        logger.info(f'Loading reference data from directory: {self.json_dir}')
        self.data = self.load_data()

    def load_data(self):
        data = {'resources': {}, 'families': {}}
        for file_path in glob.glob(os.path.join(self.json_dir, '*.json')):
            try:
                with open(file_path) as f:
                    file_data = json.load(f)
                    data['resources'].update(file_data.get('resources', {}))
                    data['families'].update(file_data.get('families', {}))
                    logger.info(
                        f'Loaded reference data file: {file_path}. Total resources: {len(data["resources"])}, families: {len(data["families"])}'
                    )
            except Exception as e:
                logger.error(f'Error loading {file_path}: {e}')
        return data

    def save_data(self):
        # Note: Saving would now need to split back to files, but for now, perhaps implement per-file save if needed.
        pass

    def get_permissions(self, entity, verb):
        if entity in self.data['families']:
            all_perms = set()
            for res in self.data['families'][entity]['resources']:
                perms = self._get_cumulative_permissions(res, verb)
                if perms:
                    all_perms.update(perms)
            return list(all_perms)
        else:
            return self._get_cumulative_permissions(entity, verb)

    def _get_cumulative_permissions(self, resource, verb):
        if resource not in self.data['resources']:
            return None
        verbs_order = ['inspect', 'read', 'use', 'manage']
        try:
            index = verbs_order.index(verb)
        except ValueError:
            return None
        perms = []
        for v in verbs_order[: index + 1]:
            perms.extend(self.data['resources'][resource]['verbs'].get(v, []))
        return list(set(perms))  # Dedup

    def check_overlap(self, perm_set1, perm_set2):
        if not perm_set1 or not perm_set2:
            return []
        overlap = {p.lower() for p in perm_set1} & {p.lower() for p in perm_set2}
        return list(overlap)

    def get_source(self, entity):
        sources = set()
        if entity in self.data['families']:
            source_url = self.data['families'][entity].get('source_url', '')
            if source_url:
                sources.add(source_url)
        else:
            for _fam, fam_data in self.data['families'].items():
                if entity in fam_data['resources']:
                    source_url = fam_data.get('source_url', '')
                    if source_url:
                        sources.add(source_url)
        return ', '.join(sources) if sources else ''
