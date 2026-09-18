"""Lifecycle boundary for the experimental compiled corpus and saved suites."""

from __future__ import annotations

import json
import threading
import time
from copy import deepcopy

from oci_policy_analysis.application.core.engine.compiled_corpus import (
    LOG_COMPONENT,
    BuildCancelled,
    CorpusRuntime,
    build_corpus,
    capture_inputs,
    checkpoint,
    digest,
)
from oci_policy_analysis.application.core.support.logger import get_logger

logger = get_logger(LOG_COMPONENT)

FILTER_FIELDS = (
    'principal',
    'scope',
    'permission',
    'effect',
    'condition',
    'conditional',
    'resource',
    'verb',
    'policy_name',
    'statement_id',
    'source_id',
)
FILTER_OPERATORS = ('contains', 'equals', 'not contains', 'not equals')
_SOURCE_FIELDS = {'resource', 'verb', 'policy_name', 'statement_id', 'source_id'}


def format_corpus_condition(predicate: dict) -> str:
    """Display the compiled Boolean tree using familiar policy syntax."""
    kind = predicate['kind']
    if kind == 'true':
        return 'Unconditional'
    if kind == 'atom':
        return predicate['expression']
    children = ', '.join(format_corpus_condition(child) for child in predicate.get('children', []))
    return f'{kind} {{ {children} }}'


def filter_corpus_grants(corpus: dict, *, query='', filters=()) -> list[dict]:
    """AND field filters, keeping provenance constraints on the same source."""
    active = [f for f in filters if str(f.get('value', '')).strip()]
    for f in active:
        if f.get('field') not in FILTER_FIELDS or f.get('operator') not in FILTER_OPERATORS:
            raise ValueError('Unknown corpus filter field or operator.')

    def matches(value, f):
        text, wanted = str(value).casefold(), str(f['value']).strip().casefold()
        operator = f['operator']
        result = wanted in text if 'contains' in operator else wanted == text
        return not result if operator.startswith('not ') else result

    source_filters = [f for f in active if f['field'] in _SOURCE_FIELDS]
    grant_filters = [f for f in active if f['field'] not in _SOURCE_FIELDS]
    terms = query.casefold().split()
    result = []
    for grant in corpus.get('grants', []):
        if not all(term in f'{grant["principal"]} {grant["scope"]} {grant["permission"]}'.casefold() for term in terms):
            continue
        predicate = corpus['predicates'][grant['predicate_id']]
        values = {
            **grant,
            'condition': format_corpus_condition(predicate),
            'conditional': 'no' if predicate['kind'] == 'true' else 'yes',
        }
        if not all(matches(values[f['field']], f) for f in grant_filters):
            continue
        if source_filters:
            for source_id in grant['source_ids']:
                provenance = corpus['sources'][source_id]
                source = provenance.get('source', {})
                values = {**source, **provenance, 'source_id': source_id}
                if all(matches(values.get(f['field'], ''), f) for f in source_filters):
                    break
            else:
                continue
        result.append(grant)
    return result


class CompiledCorpusService:
    """Publish successful builds atomically and reject evaluation of stale data."""

    def __init__(self, context):
        self.context = context
        self._runtime = None
        self._lock = threading.RLock()
        self._generation = 0
        self.stale = False

    def invalidate(self):
        with self._lock:
            was_current = self._runtime is not None and not self.stale
            self._generation += 1
            self.stale = self._runtime is not None
        if was_current:
            logger.info('Corpus invalidated: loaded data changed; rebuild required')

    def _inputs(self, *, log_capture=False):
        return capture_inputs(self.context.policy_repo, self.context.reference_data, log_capture=log_capture)

    def check_current(self):
        with self._lock:
            runtime = self._runtime
        if runtime and digest(self._inputs()) != runtime.corpus['snapshot_id']:
            if not self.stale:
                logger.info(
                    'Snapshot freshness check detected changed inputs for %s', runtime.corpus['snapshot_id'][:12]
                )
            self.invalidate()
        return runtime is not None and not self.stale

    def build(self, progress=None, cancel=None):
        started = time.perf_counter()
        logger.info('Build Compiled Corpus requested')
        try:
            corpus = self._build(progress, cancel)
        except BuildCancelled:
            logger.info('Corpus build cancelled after %.3fs; previous snapshot retained', time.perf_counter() - started)
            raise
        except Exception:
            logger.exception(
                'Corpus build failed after %.3fs; previous snapshot retained', time.perf_counter() - started
            )
            raise
        logger.info(
            'Corpus build published in %.3fs: snapshot=%s', time.perf_counter() - started, corpus['snapshot_id'][:12]
        )
        return corpus

    def _build(self, progress=None, cancel=None):
        with self._lock:
            generation = self._generation
        checkpoint(progress, cancel, 0, 100, 'Stage 1/5: Capturing loaded data')
        inputs = self._inputs(log_capture=True)
        if not inputs['inventory'].get('regular_statements') and not inputs['inventory'].get('policies'):
            raise ValueError('Load policy data before building a corpus.')
        checkpoint(progress, cancel, 10, 100, 'Stage 2/5: Compiling statements')

        def compilation_progress(done, total, message):
            checkpoint(progress, cancel, 10 + 65 * done / max(total, 1), 100, f'Stage 2/5: {message}')

        corpus = build_corpus(inputs, compilation_progress, cancel)
        checkpoint(progress, cancel, 80, 100, 'Stage 3/5: Preparing evaluation indexes')
        runtime = CorpusRuntime(corpus)
        checkpoint(progress, cancel, 90, 100, 'Stage 4/5: Verifying snapshot freshness')
        logger.info('Validating build inputs against currently loaded data')
        if digest(self._inputs()) != corpus['snapshot_id']:
            raise ValueError('Loaded data changed during the build. Build again.')
        with self._lock:
            if generation != self._generation:
                raise ValueError('Loaded data was invalidated during the build. Build again.')
            checkpoint(progress, cancel, 95, 100, 'Stage 5/5: Publishing compiled corpus')
            self._runtime = runtime
            self.stale = False
        checkpoint(progress, None, 100, 100, 'Compiled corpus ready')
        return deepcopy(corpus)

    def get_corpus(self):
        with self._lock:
            return deepcopy(self._runtime.corpus) if self._runtime else None

    def required_context(self, scenario):
        if not self.check_current():
            raise ValueError('Corpus is missing or out of date. Build Compiled Corpus first.')
        fields = self._runtime.required_context(scenario)
        if any(g['effect'] == 'deny' for g in self._runtime.candidates(scenario)):
            fields += ['corpus.deny_enabled', 'corpus.deny_exempt']
        return sorted(set(fields))

    def run_suite(self, suite, contribution=False, progress=None, cancel=None):
        logger.info('Validating corpus freshness before scenario evaluation')
        if not self.check_current():
            raise ValueError('Corpus is missing or out of date. Rebuild before evaluation.')
        with self._lock:
            runtime, generation = self._runtime, self._generation
        # Isolate caller edits and ensure suite results are JSON serializable.
        suite = json.loads(json.dumps(suite))
        try:
            result = runtime.run_suite(suite, contribution, progress, cancel)
        except BuildCancelled:
            logger.info('Scenario evaluation cancelled')
            raise
        except Exception:
            logger.exception('Scenario evaluation failed')
            raise
        if not self.check_current() or generation != self._generation:
            logger.warning('Discarding scenario results because loaded data changed during evaluation')
            raise ValueError('Loaded data changed during evaluation. Rebuild and run the suite again.')
        return result

    def open_corpus(self, corpus):
        """Open saved data for inspection; only a fresh build enables evaluation."""
        if not isinstance(corpus, dict) or not isinstance(corpus.get('inputs'), dict):
            raise ValueError('Not a compiled corpus file.')
        if digest(corpus['inputs']) != corpus.get('snapshot_id'):
            raise ValueError('Corpus snapshot checksum does not match its inputs.')
        runtime = CorpusRuntime(deepcopy(corpus))
        with self._lock:
            self._runtime = runtime
            self._generation += 1
            self.stale = True
        logger.info('Opened snapshot=%s for inspection; rebuild required before evaluation', corpus['snapshot_id'][:12])
        return self.get_corpus()
