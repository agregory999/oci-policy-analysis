"""Worker-owned contexts and asynchronous loading through the shared core."""

import json
import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from oci_policy_analysis.application.context import AppContext
from oci_policy_analysis.application.core.support.logger import get_logger
from oci_policy_analysis.application.services.load_service import LoadService
from oci_policy_analysis.presentation.qt.sample_data import sample_snapshot

logger = get_logger(component='qt.load')


class LoadWorker(QThread):
    """Own a candidate context until loading and enrichment finish in a worker."""

    progress = Signal(str, str, str)
    loaded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, source: str, options: dict, settings: dict, parent: QObject) -> None:
        """Retain load inputs and a detached copy of the session settings."""
        super().__init__(parent)
        self.source = source
        self.options = options
        self.settings = settings

    def run(self) -> None:
        """Load a fresh context and emit either a successful snapshot or an error."""
        try:
            context = AppContext.from_settings(self.settings, verbose_override=False)
            for name, level in self.settings.get('qt_runtime_log_levels', {}).items():
                logging.getLogger(name).setLevel(level)
            profile = self.settings.get('qt_post_load_profile', 'minimal')
            logger.info('Worker loading source=%s with %s enrichment', self.source, profile)
            loader = LoadService(context)
            common = {'post_load_profile': profile, 'on_stage': self.progress.emit}
            if self.source == 'oci':
                result = loader.load_from_tenancy(
                    use_instance_principal=self.options.get('auth') == 'instance_principal',
                    use_resource_principal=self.options.get('auth') == 'resource_principal',
                    profile=self.options['profile'],
                    recursive=self.options['recursive'],
                    load_all_users=self.options.get('load_all_users', True),
                    compartment_domain_search_depth=self.options['depth'],
                    save_cache_after_load=True,
                    **common,
                )
            elif self.source == 'cache':
                result = loader.load_from_cache(self.options['cache_name'], **common)
            elif self.source == 'compliance':
                result = loader.load_from_compliance_output(
                    self.options['path'], load_all_users=self.options.get('load_all_users', True), **common
                )
            elif self.source == 'sample':
                with tempfile.TemporaryDirectory(prefix='opa-qt-sample-') as directory:
                    path = Path(directory) / 'sample.json'
                    snapshot = sample_snapshot()
                    for statement in snapshot['policy_statements']:
                        statement['permission'] = context.reference_data.get_permissions(
                            statement['resource'], statement['verb'], action=statement['action']
                        )
                    path.write_text(json.dumps(snapshot), encoding='utf-8')
                    result = loader.load_from_export_json(str(path), **common)
            elif self.source == 'file':
                result = loader.load_from_export_json(self.options['path'], **common)
            else:
                raise ValueError(f'Unknown load source: {self.source}')
            if result.success:
                logger.info('Load complete: %s', result.summary)
                self.loaded.emit(context, result)
            else:
                logger.error('Load returned failure: %s', result.message)
                self.failed.emit(result.message)
        except Exception as exc:
            logger.exception('Load worker failed')
            self.failed.emit(f'{type(exc).__name__}: {exc}')
