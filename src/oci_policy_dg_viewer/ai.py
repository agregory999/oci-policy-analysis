import json
import logging
import queue
from datetime import UTC, datetime
from pathlib import Path

from oci import config
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner
from oci.exceptions import ConfigFileNotFound, ServiceError
from oci.generative_ai import GenerativeAiClient
from oci.generative_ai_inference import GenerativeAiInferenceClient
from oci.generative_ai_inference.models import (
    BaseChatRequest,
    ChatDetails,
    GenericChatRequest,
    Message,
    OnDemandServingMode,
    TextContent,
)

# Cache Directory and Date (for consistency across classes)
CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'
CACHE_FILE = CACHE_DIR / 'oci_policy_ai_cache.json'

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')
logger = logging.getLogger('oci-policy-dg-ai')


class AI:
    def __init__(self, verbose=False):
        """Initialize OCI GenAI client and constants."""
        self.verbose = verbose
        logger.info('Initialized AI Module')

        # Load the cache internally
        self.load_cache()

        # Mark not initialized
        self.initialized = False

    def initialize_client(self, use_instance_principal: bool, profile: str = 'DEFAULT') -> bool:
        try:
            if use_instance_principal:
                logger.debug('Using Instance Principal Authentication for AI')
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.genai_client = GenerativeAiClient(config={}, signer=self.signer)
                self.genai_inference_client = GenerativeAiInferenceClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
                self.region = self.signer.region
            else:
                logger.debug(f'Using Profile Authentication for AI: {profile}')
                self.config = config.from_file(profile_name=profile)
                self.genai_client = GenerativeAiClient(self.config)
                self.genai_inference_client = GenerativeAiInferenceClient(self.config)
                self.tenancy_ocid = self.config['tenancy']
                self.region = self.config['region']
            logger.info(f'Set up GenAI and Inference Client for tenancy: {self.tenancy_ocid}')

            # Set up base endpoint
            self.base_endpoint = f'https://inference.generativeai.{self.region}.oci.oraclecloud.com'
            self.initialized = True
            return True
        except (ConfigFileNotFound, Exception) as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    def update_config(self, model_ocid, endpoint, compartment_ocid):
        """Update Model ID and Endpoint, reinitializing client if endpoint changes."""
        logger.info(
            f'Updating AI config: Model OCID:{model_ocid}, Endpoint:{endpoint}, Compartment: {compartment_ocid}'
        )
        self.model_ocid = model_ocid
        self.endpoint = endpoint
        self.compartment_ocid = compartment_ocid

    def create_chat_request(self, prompt):
        # Create Chat Details
        chat_detail = ChatDetails()
        chat_detail.serving_mode = OnDemandServingMode(model_id=self.model_ocid)

        content = TextContent()
        content.text = prompt

        chat_request = GenericChatRequest()
        chat_request.api_format = BaseChatRequest.API_FORMAT_GENERIC
        chat_request.messages = [Message(role='USER', content=[content])]
        chat_request.max_tokens = 1500
        chat_request.temperature = 0
        chat_request.top_p = 0.25
        chat_request.top_k = 0

        chat_detail.chat_request = chat_request
        chat_detail.compartment_id = self.compartment_ocid
        logger.info(f'Created Chat Request with prompt: {prompt}')
        logger.debug(f'Created Chat: {chat_detail}')
        return chat_detail

    def list_models(self) -> list[dict]:
        """List available models using GenerativeAiClient.list_models."""
        logger.info('Listing available models')
        try:
            # Try to list models from tenancy
            response = self.genai_client.list_models(compartment_id=self.tenancy_ocid)
            models = [
                {
                    'Model Name': model.display_name or 'Unknown',
                    'Model OCID': model.id,
                    'Lifecycle State': model.lifecycle_state or 'N/A',
                    'Creation Date': model.time_created.isoformat() if model.time_created else 'N/A',
                }
                for model in response.data.items
            ]
            # for model in models:
            #     self.model_name_cache[model['id']] = model['display_name']
            logger.info('Retrieved %d models from list_models', len(models))
            return models
        except ServiceError as e:
            logger.error('Service error listing models: %s', e)
            raise
        except Exception as e:
            logger.error('Error listing models: %s', e)
            raise

    def load_cache(self):
        """Load AI query cache from persistent file if available, else return empty list."""
        logger.debug('Loading cache from %s', CACHE_FILE)
        try:
            # Ensure cache directory exists
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE) as f:
                self.ai_result_cache = json.load(f)
                if not isinstance(self.ai_result_cache, list):
                    logger.warning('Cache file %s is not a list, returning empty list', CACHE_FILE)
                    # return []
                logger.info('Successfully loaded cache with %d entries', len(self.ai_result_cache))

            # TO-DO: remove older entries from cache
            for entry in self.ai_result_cache:
                if 'date_ms' in entry:
                    # Just show the date for logging purposes
                    logger.debug(
                        f"Cache entry date: {datetime.fromtimestamp(entry['date_ms'] / 1000, UTC).isoformat()}"
                    )

        except FileNotFoundError:
            logger.debug('Cache file %s not found, returning empty list', CACHE_FILE)
            self.ai_result_cache = []
        except json.JSONDecodeError as e:
            logger.error('Failed to parse JSON from %s: %s', CACHE_FILE, e)
            self.ai_result_cache = []

    def save_cache(self):
        """Save AI query cache to persistent file each time a query occurs."""
        logger.debug('Saving cache to %s', CACHE_FILE)
        try:
            with open(CACHE_FILE, 'w') as f:
                json.dump(self.ai_result_cache, f, indent=4)
            logger.info('Successfully saved cache to %s with %d entries', CACHE_FILE, len(self.ai_result_cache))
        except Exception as e:
            logger.error('Failed to save cache to %s: %s', CACHE_FILE, e)

    def analyze_policy_statement(  # noqa: C901
        self, policy_text: str, queue: queue.Queue, use_cache: bool = False, additional_instruction: str = ''
    ):  # noqa: C901
        """Call OCI GenAI to analyze an OCI IAM policy statement, using cache if available. Put the results on a Queue that is provided"""
        logger.info('Analyzing policy statement: %s', policy_text)

        if use_cache:
            for entry in self.ai_result_cache:
                if entry.get('type') == 'analyze_policy_statement' and entry.get('query') == policy_text:
                    logger.debug('Cache hit for policy analysis: %s', policy_text)
                    return entry['result']

        start_time = datetime.now()
        logger.info(f'Calling OCI GenAI for policy analysis: {policy_text}')
        prompt = (
            f"Describe OCI Policy permission '{policy_text}' in detail, including what it allows, typical use cases, and any important considerations. "
            'Format the response in markdown with clear sections using headers (##). '
            f'{additional_instruction} '
            'Use unordered lists (- item) for permissions and use cases, ensuring each list item has meaningful content and no empty items. '
            "Include a direct documentation link if available under a 'Documentation' section. "
            'Avoid empty lines in lists and ensure all content is concise and relevant.'
        )
        chat_detail = self.create_chat_request(prompt=prompt)
        # Make the request
        try:
            response = self.genai_inference_client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content

            logger.debug('Raw API response type: %s, content: %s', type(raw_content), str(raw_content)[:1000])

            # Process result
            if isinstance(raw_content, list):
                logger.debug('Raw content is a list with length %d', len(raw_content))
                if len(raw_content) > 0:
                    first_item = raw_content[0]
                    logger.debug('First item type: %s', type(first_item))
                    if hasattr(first_item, 'text'):
                        result = first_item.text
                        logger.debug(f"Extracted 'text' attribute from first item: {policy_text} = {result[:100]}")
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        result = first_item['text']
                        logger.debug("Extracted 'text' key from first dict: %s", result[:100])
                    else:
                        logger.debug(
                            "First item lacks 'text' attribute or key, using str(first_item) as fallback: %s",
                            str(first_item)[:100],
                        )
                        result = str(first_item)
                else:
                    logger.debug(
                        'List response is empty, using str(raw_content) as fallback: %s', str(raw_content)[:100]
                    )
                    result = str(raw_content)
            elif isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                    logger.debug(
                        'Parsed JSON content type: %s, content: %s', type(parsed_content), str(parsed_content)[:1000]
                    )
                    if isinstance(parsed_content, dict) and 'text' in parsed_content:
                        result = parsed_content['text']
                        logger.debug("Extracted 'text' field from JSON: %s", result[:100])
                    elif isinstance(parsed_content, list) and len(parsed_content) > 0:
                        first_item = parsed_content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            result = first_item['text']
                            logger.debug("Extracted 'text' field from JSON list: %s", result[:100])
                        else:
                            logger.debug(
                                "No 'text' field in JSON list, using raw content as fallback: %s", raw_content[:100]
                            )
                            result = raw_content
                    else:
                        result = raw_content
                        logger.debug('Treating raw content as plain string: %s', result[:100])
                except json.JSONDecodeError:
                    result = raw_content
                    logger.debug('Raw content is not JSON, using as-is: %s', result[:100])
            elif isinstance(raw_content, dict):
                logger.debug('Raw content is dict: %s', str(raw_content)[:1000])
                if 'text' in raw_content:
                    result = raw_content['text']
                    logger.debug("Extracted 'text' field from dict: %s", result[:100])
                else:
                    logger.debug(
                        "Dictionary response lacks 'text' field, using str(raw_content) as fallback: %s",
                        str(raw_content)[:100],
                    )
                    result = str(raw_content)
            else:
                logger.error('Unexpected response format: %s', type(raw_content))
                result = f'Error: Unexpected API response format: {type(raw_content)}'

            if not isinstance(result, str):
                logger.error('Extracted content is not a string: type=%s, content=%s', type(result), str(result)[:1000])
                result = f'Error: Extracted content is not a string: {type(result)}'

            logger.debug('Final result type: %s, content: %s', type(result), result[:100])

            # Add to cache if success
            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'analyze_policy_statement',
                    'query': policy_text,
                    'result': result,
                    'date_ms': int(datetime.now().timestamp() * 1000),
                }
            )
            self.save_cache()

            logger.info('Completed policy analysis in %s seconds', (datetime.now() - start_time).total_seconds())
            # if queue:
            #     queue.put(result)
            # else:
            #     return result
        except ServiceError as e:
            if e.status == 404:
                logger.error('OCI GenAI returned 404 for policy analysis: %s', e)
                result = f'<p>Error: Policy analysis failed (404) - likely this is a permission issue.  Make sure that the Profile API or Instance Principal user has \
<code>allow group PolicyUsers to use generative-ai in tenancy</code><br/>If you enable DEBUG and run again, you will see the entire message below. <br/>{e if self.verbose else ""}<p>'
                # if queue:
                #     queue.put(result)
                # else:
                #     return result
            else:
                logger.error('Error calling OCI GenAI for policy analysis: %s', e)
                result = f'Error calling OCI GenAI: {str(e)}'
            logger.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
            # return result
        except Exception as e:
            logger.error('Error calling OCI GenAI for policy analysis: %s', e)
            result = f'Error calling OCI GenAI: {str(e)}'
            logger.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
        # Put on queue if it is there or return the result
        if queue:
            queue.put(result)
        else:
            return result

    def test_ai_call(self, query: str, queue: queue.Queue, use_cache: bool = False, additional_instruction: str = ''):  # noqa: C901
        """Call OCI GenAI to test AI functionality. Put the results on a Queue that is provided"""
        logger.info(f'Given Prompt: {query}, Additional Instruction: {additional_instruction}')

        start_time = datetime.now()
        prompt = (
            f'{query} '
            f'{additional_instruction} '
            'return strict markdown format with no empty lines.'
            'markdown should include sections with headers (##) and unordered lists (* item).'
            'return a web link if relevant.'
        )
        chat_detail = self.create_chat_request(prompt=prompt)
        # Make the request
        try:
            response = self.genai_inference_client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content

            logger.debug('Raw API response type: %s, content: %s', type(raw_content), str(raw_content)[:1000])

            # Process result
            if isinstance(raw_content, list):
                logger.debug('Raw content is a list with length %d', len(raw_content))
                if len(raw_content) > 0:
                    first_item = raw_content[0]
                    logger.debug('First item type: %s', type(first_item))
                    if hasattr(first_item, 'text'):
                        result = first_item.text
                        logger.debug(f"Extracted 'text' attribute from first item: {result[:100]}")
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        result = first_item['text']
                        logger.debug("Extracted 'text' key from first dict: %s", result[:100])
                    else:
                        logger.debug(
                            "First item lacks 'text' attribute or key, using str(first_item) as fallback: %s",
                            str(first_item)[:100],
                        )
                        result = str(first_item)
                else:
                    logger.debug(
                        'List response is empty, using str(raw_content) as fallback: %s', str(raw_content)[:100]
                    )
                    result = str(raw_content)
            elif isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                    logger.debug(
                        'Parsed JSON content type: %s, content: %s', type(parsed_content), str(parsed_content)[:1000]
                    )
                    if isinstance(parsed_content, dict) and 'text' in parsed_content:
                        result = parsed_content['text']
                        logger.debug("Extracted 'text' field from JSON: %s", result[:100])
                    elif isinstance(parsed_content, list) and len(parsed_content) > 0:
                        first_item = parsed_content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            result = first_item['text']
                            logger.debug("Extracted 'text' field from JSON list: %s", result[:100])
                        else:
                            logger.debug(
                                "No 'text' field in JSON list, using raw content as fallback: %s", raw_content[:100]
                            )
                            result = raw_content
                    else:
                        result = raw_content
                        logger.debug('Treating raw content as plain string: %s', result[:100])
                except json.JSONDecodeError:
                    result = raw_content
                    logger.debug('Raw content is not JSON, using as-is: %s', result[:100])
            elif isinstance(raw_content, dict):
                logger.debug('Raw content is dict: %s', str(raw_content)[:1000])
                if 'text' in raw_content:
                    result = raw_content['text']
                    logger.debug("Extracted 'text' field from dict: %s", result[:100])
                else:
                    logger.debug(
                        "Dictionary response lacks 'text' field, using str(raw_content) as fallback: %s",
                        str(raw_content)[:100],
                    )
                    result = str(raw_content)
            else:
                logger.error('Unexpected response format: %s', type(raw_content))
                result = f'Error: Unexpected API response format: {type(raw_content)}'

            if not isinstance(result, str):
                logger.error('Extracted content is not a string: type=%s, content=%s', type(result), str(result)[:1000])
                result = f'Error: Extracted content is not a string: {type(result)}'

            logger.debug('Final result type: %s, content: %s', type(result), result[:100])

            logger.info('Completed test call in %s seconds', (datetime.now() - start_time).total_seconds())

        except ServiceError as e:
            if e.status == 404:
                logger.error('OCI GenAI returned 404 for policy analysis: %s', e)
                result = f'<p>Error: Policy analysis failed (404) - likely this is a permission issue.  Make sure that the Profile API or Instance Principal user has access to use generative-ai in tenancy.<br/>If you enable DEBUG and run again, you will see the entire message below. <br/>{e if logger.level == logger.debug else ""}<p>'

            else:
                logger.error('Error calling OCI GenAI for policy analysis: %s', e)
                result = f'Error calling OCI GenAI: {str(e)}'
            logger.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
        except Exception as e:
            logger.error('Error calling OCI GenAI for policy analysis: %s', e)
            result = f'Error calling OCI GenAI: {str(e)}'
            logger.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )

        # Put on queue if it is there or return the result
        if queue:
            queue.put(result)
        else:
            return result
