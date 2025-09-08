import asyncio
import json
import logging
from datetime import UTC, datetime

from data import OCIDataService
from oci.exceptions import ServiceError
from oci.generative_ai_inference import GenerativeAiInferenceClient
from oci.generative_ai_inference.models import (
    ChatDetails,
    GenericChatRequest,
    Message,
    OnDemandServingMode,
    TextContent,
)
from utils import load_cache, log_handler, logger, save_cache


class IAMService:
    def __init__(self, data_service: OCIDataService):
        self.data_service = data_service
        self.compartment_id = self.data_service.compartment_id
        self.cache = {'policies': [], 'users': [], 'groups': [], 'dynamic_groups': [], 'ai_cache': []}
        default_endpoint = 'https://generativeai.us-ashburn-1.oci.oraclecloud.com'
        default_model = 'grok'
        endpoint = (
            self.data_service.config.get('ai_endpoint', default_endpoint)
            if self.data_service.config
            else default_endpoint
        )
        model = self.data_service.config.get('model_ocid', default_model) if self.data_service.config else default_model
        self.update_ai_config(endpoint, model)

    def update_ai_config(self, endpoint, model_ocid):
        """Update the Generative AI client with new endpoint and model OCID."""
        default_endpoint = 'https://generativeai.us-ashburn-1.oci.oraclecloud.com'
        default_model = 'grok'
        self.model = model_ocid or default_model
        endpoint = endpoint or default_endpoint
        try:
            auth_mode = getattr(
                self.data_service, 'auth_mode', 'profile'
            )  # Fallback to 'profile' if auth_mode is missing
            logger.debug(f'Updating AI client with auth_mode: {auth_mode}, endpoint: {endpoint}, model: {self.model}')
            if auth_mode == 'instance_principal':
                if not hasattr(self.data_service, 'signer') or self.data_service.signer is None:
                    logger.error('No signer available for instance principal authentication')
                    self.client = None
                    return
                self.client = GenerativeAiInferenceClient(
                    config={}, signer=self.data_service.signer, service_endpoint=endpoint
                )
            else:
                if not self.data_service.config:
                    logger.error('No config available for profile-based authentication')
                    self.client = None
                    return
                self.client = GenerativeAiInferenceClient(config=self.data_service.config, service_endpoint=endpoint)
            logger.info(f'Generative AI client updated with endpoint: {endpoint}, model: {self.model}')
        except Exception as e:
            logger.error(f'Failed to update Generative AI client: {e}')
            self.client = None

    def post_process_policies(self, policies):
        """Post-process policy data."""
        processed_policies = []
        for policy in policies:
            processed_policy = {
                'name': policy.name,
                'statements': policy.statements,
                'compartment_id': policy.compartment_id,
                'creation_date': policy.time_created.isoformat() if policy.time_created else 'N/A',
            }
            processed_policy['statement_count'] = len(policy.statements) if policy.statements else 0
            processed_policies.append(processed_policy)
        return processed_policies

    def load_data(self, compartment_id, auth_mode='profile', cache_name=None):
        """Load IAM data based on mode with post-processing."""
        if auth_mode == 'cache' and cache_name:
            cached_data = load_cache(cache_name)
            if cached_data:
                self.cache.update(cached_data)
                logger.info(f'Loaded IAM data from cache {cache_name}')
                return
        try:
            raw_policies = self.data_service.list_policies(compartment_id)
            self.cache['policies'] = self.post_process_policies(raw_policies)
            self.cache['users'] = self.data_service.list_users()
            self.cache['groups'] = self.data_service.list_groups()
            self.cache['dynamic_groups'] = self.data_service.list_dynamic_groups()
            cache_date = datetime.now().strftime('%Y%m%d-%H%M%S')
            new_cache_name = f'cache-{compartment_id}-{cache_date}'
            save_cache({k: v for k, v in self.cache.items() if k != 'ai_cache'}, new_cache_name)
            logger.info(f'IAM data loaded and cached as {new_cache_name}')
        except Exception as e:
            logger.error(f'Error loading IAM data: {e}')
            raise

    def get_domains(self):
        """Return list of domain names for UI dropdown."""
        domains = ['Users', 'Groups', 'Dynamic Groups', 'Policies']
        return domains

    def filter_policies_by_verb(self, verb):
        """Filter policies by verb (e.g., 'manage', 'use')."""
        if not verb:
            return self.cache['policies']
        filtered = [
            policy
            for policy in self.cache['policies']
            if any(verb.lower() in statement.lower() for statement in policy['statements'])
        ]
        logger.info(f"Filtered {len(filtered)} policies by verb '{verb}'")
        return filtered

    def filter_by_name(self, entity_type, name_substring):
        """Filter users, groups, or dynamic groups by name substring."""
        entity_map = {'Users': 'users', 'Groups': 'groups', 'Dynamic Groups': 'dynamic_groups', 'Policies': 'policies'}
        cache_key = entity_map.get(entity_type)
        if not cache_key:
            logger.error(f'Invalid entity type: {entity_type}')
            return []
        if not name_substring:
            return self.cache[cache_key]
        filtered = [entity for entity in self.cache[cache_key] if name_substring.lower() in entity['name'].lower()]
        logger.info(f"Filtered {len(filtered)} {entity_type} by name '{name_substring}'")
        return filtered

    def get_policies_for_table(self, verb_filter=''):
        """Prepare policies for table display."""
        policies = self.filter_policies_by_verb(verb_filter)
        return policies

    def get_entities_for_table(self, entity_type, name_filter=''):
        """Prepare users, groups, or dynamic groups for table display."""
        entities = self.filter_by_name(entity_type, name_filter)
        return entities

    async def get_ai_insights(self, policy_name):
        """Generate AI insights for a policy using OCI Generative AI."""
        try:
            policies = [p for p in self.cache['policies'] if p['name'] == policy_name]
            if not policies:
                return 'Policy not found.'
            policy = policies[0]
            text = '; '.join(policy['statements'])
            prompt = f'Summarize this OCI policy: {text}'
            cache_type = 'policy_summary'
            cache_query = policy_name
            start_time = datetime.now()
            logger.debug('Querying GenAI with prompt: %s', prompt[:100])
            for entry in self.cache['ai_cache']:
                if entry.get('type') == cache_type and entry.get('query') == cache_query:
                    logger.debug('Cache hit for %s: %s', cache_type, cache_query[:100])
                    return entry.get('result', 'Error: Cache entry missing result')
            params = {'max_tokens': 4096, 'temperature': 0.7, 'top_p': 0.95, 'top_k': 50}
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: self.query_genai(prompt, cache_type, cache_query, self.cache['ai_cache'], **params)
            )
            logging.info('Query completed in %s seconds', (datetime.now() - start_time).total_seconds())
            return result
        except Exception as e:
            logger.error(f'Error generating AI insights: {e}')
            return f'**Error**: Failed to generate insights: {str(e)}'

    def query_genai(self, prompt, cache_type=None, cache_query=None, cache=None, **kwargs):  # noqa: C901
        """Query OCI Generative AI with a prompt, optionally caching the result."""
        start_time = datetime.now()
        logging.debug('Querying GenAI with prompt: %s', prompt)
        cache = cache if cache is not None else self.cache['ai_cache']
        if cache_type and cache_query and cache:
            for entry in cache:
                if entry.get('type') == cache_type and entry.get('query') == cache_query:
                    logging.debug('Cache hit for %s: %s', cache_type, cache_query[:100])
                    return entry.get('result', 'Error: Cache entry missing result')
        if not self.client:
            result = 'Error: AI client not initialized'
            logging.error(result)
            return result
        params = {'max_tokens': 4096, 'temperature': 0.7, 'top_p': 0.95, 'top_k': 50}
        params.update(kwargs)
        try:
            chat_detail = ChatDetails()
            chat_detail.serving_mode = OnDemandServingMode(model_id=self.model)
            content = TextContent()
            content.text = f'{prompt}\n\nProvide the response in strict markdown format. Avoid empty lines in lists and ensure all content is concise and relevant. Format the policy statement in a code block (```) with no code type specified. Use unordered lists (- item) for descriptions, ensuring each list item has meaningful content and no empty items.'
            chat_request = GenericChatRequest()
            chat_request.api_format = GenericChatRequest.API_FORMAT_GENERIC
            chat_request.messages = [Message(role='USER', content=[content])]
            for key, value in params.items():
                setattr(chat_request, key, value)
            chat_detail.chat_request = chat_request
            chat_detail.compartment_id = self.compartment_id
            response = self.client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content
            logging.info(f'Raw content type: {type(raw_content)}')
            logging.info(f'Raw content length: {len(raw_content)}')
            if isinstance(raw_content, list) and len(raw_content) > 0 and isinstance(raw_content[0], TextContent):
                resp_json = json.loads(str(raw_content[0]))
                resp_text = resp_json['text']
                logging.info('Extracted markdown: %s', resp_text[:100])
            else:
                resp_text = f'Error: Unexpected API response format: {type(raw_content)}'
                logging.error(resp_text)
            if cache_type and cache_query and cache is not None:
                cache.append(
                    {
                        'date': datetime.now(UTC).isoformat(),
                        'type': cache_type,
                        'query': cache_query,
                        'result': resp_text,
                    }
                )
            logging.info('Query completed in %s seconds', (datetime.now() - start_time).total_seconds())
            return resp_text
        except ServiceError as e:
            result = f'Error: API call failed ({e.status}): {str(e)}'
            logging.error(result)
            if cache_type and cache_query and cache is not None:
                cache.append(
                    {'date': datetime.now(UTC).isoformat(), 'type': cache_type, 'query': cache_query, 'result': result}
                )
            return result
        except Exception as e:
            result = f'Error: {str(e)}'
            logging.error(result)
            if cache_type and cache_query and cache is not None:
                cache.append(
                    {'date': datetime.now(UTC).isoformat(), 'type': cache_type, 'query': cache_query, 'result': result}
                )
            return result

    def save_cache(self, cache):
        """Save AI cache to a separate file (optional, not implemented)."""
        pass

    def get_console_logs(self, log_level='INFO'):
        """Return cached logs for display based on log level."""
        logs = log_handler.short_logs[-10:] if log_level == 'INFO' else log_handler.logs[-10:]
        return '\n'.join(logs)
