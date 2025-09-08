import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import oci

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s [%(threadName)s] %(levelname)s %(message)s')


class AI:
    def __init__(self, verbose=False):
        """Initialize OCI GenAI client and constants."""
        self.COMPARTMENT_ID = 'ocid1.compartment.oc1..aaaaaaaazgn5vtlrndakdili7vvsvstsr5p3t7nsm56wummhuk4tb5rgrfda'
        self.AI_MODEL_ID = (
            'ocid1.generativeaimodel.oc1.us-chicago-1.amaaaaaask7dceyat326ygnn5hesfplopdmkyrklzcehzxhk5262655bthjq'
        )
        self.CACHE_DIR = Path.home() / '.oci-policy-analysis' / 'cache'

        self.CACHE_FILE = self.CACHE_DIR / 'oci_policy_ai_cache.json'
        self.model_name_cache = {}  # Cache for model OCID to display_name
        self.verbose = verbose
        try:
            self.config = oci.config.from_file()
            self.client = oci.generative_ai_inference.GenerativeAiInferenceClient(self.config)
            logging.info('Initialized OCI GenAI client')
        except Exception as e:
            logging.error('Error initializing OCI GenAI client: %s', e)
            raise

        # Load the cache internally
        self.load_cache()

    def update_config(self, model_id, endpoint):
        """Update Model ID and Endpoint, reinitializing client if endpoint changes."""
        logging.info('Updating AI config: Model ID=%s, Endpoint=%s', model_id, endpoint)
        if model_id:
            self.AI_MODEL_ID = model_id
            if model_id in self.model_name_cache:
                del self.model_name_cache[model_id]
            logging.debug('Updated AI_MODEL_ID to %s', model_id)
        if endpoint and endpoint != self.client.base_client.endpoint:
            try:
                self.config['endpoint'] = endpoint
                self.client = oci.generative_ai_inference.GenerativeAiInferenceClient(self.config)
                logging.info('Reinitialized OCI GenAI client with new endpoint')
            except Exception as e:
                logging.error('Failed to reinitialize client with new endpoint: %s', e)
                raise

    def list_models(self):
        """List available models using GenerativeAiClient.list_models."""
        logging.info('Listing available models')
        try:
            gen_ai_client = oci.generative_ai.GenerativeAiClient(self.config)
            response = gen_ai_client.list_models(self.COMPARTMENT_ID)
            models = [
                {
                    'display_name': model.display_name or 'Unknown',
                    'id': model.id,
                    'lifecycle_state': model.lifecycle_state or 'N/A',
                    'time_created': model.time_created.isoformat() if model.time_created else 'N/A',
                }
                for model in response.data.items
            ]
            for model in models:
                self.model_name_cache[model['id']] = model['display_name']
            logging.info('Retrieved %d models from list_models', len(models))
            return models
        except oci.exceptions.ServiceError as e:
            logging.error('Service error listing models: %s', e)
            raise
        except Exception as e:
            logging.error('Error listing models: %s', e)
            raise

    def get_model_name(self, model_id):
        """Get the display name for a model OCID, using cache or list_models."""
        logging.debug('Getting model name for OCID: %s', model_id)
        if model_id in self.model_name_cache:
            logging.debug('Cache hit for model name: %s', self.model_name_cache[model_id])
            return self.model_name_cache[model_id]

        try:
            models = self.list_models()
            for model in models:
                if model['id'] == model_id:
                    self.model_name_cache[model_id] = model['display_name']
                    logging.debug('Found model name: %s for OCID: %s', model['display_name'], model_id)
                    return model['display_name']
            logging.warning("Model OCID %s not found, returning 'Unknown'", model_id)
            self.model_name_cache[model_id] = 'Unknown'
            return 'Unknown'
        except Exception as e:
            logging.error('Error getting model name for OCID %s: %s', model_id, e)
            self.model_name_cache[model_id] = 'Unknown'
            return 'Unknown'

    def load_cache(self):
        """Load AI query cache from persistent file if available, else return empty list."""
        logging.debug('Loading cache from %s', self.CACHE_FILE)
        try:
            with open(self.CACHE_FILE) as f:
                self.ai_result_cache = json.load(f)
                if not isinstance(self.ai_result_cache, list):
                    logging.warning('Cache file %s is not a list, returning empty list', self.CACHE_FILE)
                    # return []
                logging.info('Successfully loaded cache with %d entries', len(self.ai_result_cache))
                # return cache/
        except FileNotFoundError:
            logging.debug('Cache file %s not found, returning empty list', self.CACHE_FILE)
            self.ai_result_cache = []
        except json.JSONDecodeError as e:
            logging.error('Failed to parse JSON from %s: %s', self.CACHE_FILE, e)
            self.ai_result_cache = []

    def save_cache(self):
        """Save AI query cache to persistent file each time a query occurs."""
        logging.debug('Saving cache to %s', self.CACHE_FILE)
        try:
            with open(self.CACHE_FILE, 'w') as f:
                json.dump(self.ai_result_cache, f, indent=4)
            logging.info('Successfully saved cache to %s with %d entries', self.CACHE_FILE, len(self.ai_result_cache))
        except Exception as e:
            logging.error('Failed to save cache to %s: %s', self.CACHE_FILE, e)

    def describe_resource(self, resource):  # noqa: C901
        """Call OCI GenAI to describe the OCI Policy resource, using cache if available."""
        logging.info('Describing resource: %s', resource)

        for entry in self.ai_result_cache:
            if entry.get('type') == 'describe_resource' and entry.get('query') == resource:
                logging.debug('Cache hit for resource: %s', resource)
                return entry['result']

        start_time = datetime.now()
        logging.info('Calling OCI GenAI for resource description: %s', resource)
        try:
            chat_detail = oci.generative_ai_inference.models.ChatDetails()
            chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(model_id=self.AI_MODEL_ID)

            content = oci.generative_ai_inference.models.TextContent()
            content.text = (
                f"Describe OCI Policy permission '{resource}' in detail, including what it allows, typical use cases, and any important considerations. "
                'Format the response in markdown with clear sections using headers (##). '
                'Use unordered lists (- item) for permissions and use cases, ensuring each list item has meaningful content and no empty items. '
                "Include a direct documentation link if available under a 'Documentation' section. "
                'Avoid empty lines in lists and ensure all content is concise and relevant.'
            )

            chat_request = oci.generative_ai_inference.models.GenericChatRequest()
            chat_request.api_format = oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC
            chat_request.messages = [oci.generative_ai_inference.models.Message(role='USER', content=[content])]
            chat_request.max_tokens = 1000
            chat_request.temperature = 1
            chat_request.top_p = 1
            chat_request.top_k = 0

            chat_detail.chat_request = chat_request
            chat_detail.compartment_id = self.COMPARTMENT_ID

            logging.info('Sending OCI GenAI API request for resource description')
            response = self.client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content

            logging.info('Raw API response type: %s, content: %s', type(raw_content), str(raw_content)[:1000])

            if isinstance(raw_content, list):
                logging.debug('Raw content is a list with length %d', len(raw_content))
                if len(raw_content) > 0:
                    first_item = raw_content[0]
                    logging.debug('First item type: %s', type(first_item))
                    if hasattr(first_item, 'text'):
                        result = first_item.text
                        logging.debug("Extracted 'text' attribute from first item: %s", result[:100])
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        result = first_item['text']
                        logging.debug("Extracted 'text' key from first dict: %s", result[:100])
                    else:
                        logging.debug(
                            "First item lacks 'text' attribute or key, using str(first_item) as fallback: %s",
                            str(first_item)[:100],
                        )
                        result = str(first_item)
                else:
                    logging.debug(
                        'List response is empty, using str(raw_content) as fallback: %s', str(raw_content)[:100]
                    )
                    result = str(raw_content)
            elif isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                    logging.debug(
                        'Parsed JSON content type: %s, content: %s', type(parsed_content), str(parsed_content)[:1000]
                    )
                    if isinstance(parsed_content, dict) and 'text' in parsed_content:
                        result = parsed_content['text']
                        logging.debug("Extracted 'text' field from JSON: %s", result[:100])
                    elif isinstance(parsed_content, list) and len(parsed_content) > 0:
                        first_item = parsed_content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            result = first_item['text']
                            logging.debug("Extracted 'text' field from JSON list: %s", result[:100])
                        else:
                            logging.debug(
                                "No 'text' field in JSON list, using raw content as fallback: %s", raw_content[:100]
                            )
                            result = raw_content
                    else:
                        result = raw_content
                        logging.debug('Treating raw content as plain string: %s', result[:100])
                except json.JSONDecodeError:
                    result = raw_content
                    logging.debug('Raw content is not JSON, using as-is: %s', result[:100])
            elif isinstance(raw_content, dict):
                logging.debug('Raw content is dict: %s', str(raw_content)[:1000])
                if 'text' in raw_content:
                    result = raw_content['text']
                    logging.debug("Extracted 'text' field from dict: %s", result[:100])
                else:
                    logging.debug(
                        "Dictionary response lacks 'text' field, using str(raw_content) as fallback: %s",
                        str(raw_content)[:100],
                    )
                    result = str(raw_content)
            else:
                logging.error('Unexpected response format: %s', type(raw_content))
                result = f'Error: Unexpected API response format: {type(raw_content)}'

            if not isinstance(result, str):
                logging.error(
                    'Extracted content is not a string: type=%s, content=%s', type(result), str(result)[:1000]
                )
                result = f'Error: Extracted content is not a string: {type(result)}'

            logging.debug('Final result type: %s, content: %s', type(result), result[:100])

            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'describe_resource',
                    'query': resource,
                    'result': result,
                }
            )
            # Write the cache to disk
            self.save_cache()

            logging.info('Completed resource description in %s seconds', (datetime.now() - start_time).total_seconds())
            return result
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                logging.error('OCI GenAI returned 404 for resource %s: %s', resource, e)
                result = f"Error: Permission '{resource}' not found in OCI GenAI (404)"
            else:
                logging.error('Error calling OCI GenAI for %s: %s', resource, e)
                result = f'Error calling OCI GenAI: {str(e)}'
            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'describe_resource',
                    'query': resource,
                    'result': result,
                }
            )
            self.save_cache()
            logging.info(
                'Completed resource description (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
            return result
        except Exception as e:
            logging.error('Error calling OCI GenAI for %s: %s', resource, e)
            result = f'Error calling OCI GenAI: {str(e)}'
            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'describe_resource',
                    'query': resource,
                    'result': result,
                }
            )
            self.save_cache()
            logging.info(
                'Completed resource description (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
            return result

    def generate_policy_statement(self, resource=None):  # noqa: C901
        """Call OCI GenAI to generate sample OCI IAM policy statements for a resource, using cache if available."""
        if resource is None:
            resource = 'general'
        logging.info('Generating sample policy statements for resource: %s', resource)

        for entry in self.ai_result_cache:
            if entry.get('type') == 'generate_policy_statement' and entry.get('query') == resource:
                logging.debug('Cache hit for policy statement generation for resource: %s', resource)
                return entry['result']

        start_time = datetime.now()
        logging.info('Calling OCI GenAI for policy statement generation for resource: %s', resource)
        try:
            chat_detail = oci.generative_ai_inference.models.ChatDetails()
            chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(model_id=self.AI_MODEL_ID)

            content = oci.generative_ai_inference.models.TextContent()
            content.text = (
                f"Generate 2-3 sample OCI IAM policy statements for '{resource}'."
                'For each statement, provide a markdown description with headers (##) explaining what the policy does, its use case, and any considerations. '
                "Format the policy statement in a code block (```) with no code type specified with comments at the end of the policy starting with '///'. End the code block (```) after the statement."
                'Below the code block, use markdown unordered lists (- item) for the description, ensuring each list item has meaningful content and no empty items. '
                'Use unordered lists (- item) for descriptions, ensuring each list item has meaningful content and no empty items. '
                "Include a 'Documentation' section with a direct link if available. Verify that the link is correct."
                'Avoid empty lines in lists and ensure all content is concise and relevant.'
            )

            chat_request = oci.generative_ai_inference.models.GenericChatRequest()
            chat_request.api_format = oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC
            chat_request.messages = [oci.generative_ai_inference.models.Message(role='USER', content=[content])]
            chat_request.max_tokens = 1000
            chat_request.temperature = 1
            chat_request.top_p = 1
            chat_request.top_k = 0

            chat_detail.chat_request = chat_request
            chat_detail.compartment_id = self.COMPARTMENT_ID

            logging.debug('Sending OCI GenAI API request for policy statement generation')
            response = self.client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content

            logging.debug('Raw API response type: %s, content: %s', type(raw_content), str(raw_content))

            if isinstance(raw_content, list):
                logging.debug('Raw content is a list with length %d', len(raw_content))
                if len(raw_content) > 0:
                    first_item = raw_content[0]
                    logging.debug('First item type: %s', type(first_item))
                    if hasattr(first_item, 'text'):
                        result = first_item.text
                        logging.debug("Extracted 'text' attribute from first item: %s", result[:100])
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        result = first_item['text']
                        logging.debug("Extracted 'text' key from first dict: %s", result[:100])
                    else:
                        logging.debug(
                            "First item lacks 'text' attribute or key, using str(first_item) as fallback: %s",
                            str(first_item)[:100],
                        )
                        result = str(first_item)
                else:
                    logging.debug(
                        'List response is empty, using str(raw_content) as fallback: %s', str(raw_content)[:100]
                    )
                    result = str(raw_content)
            elif isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                    logging.debug(
                        'Parsed JSON content type: %s, content: %s', type(parsed_content), str(parsed_content)[:1000]
                    )
                    if isinstance(parsed_content, dict) and 'text' in parsed_content:
                        result = parsed_content['text']
                        logging.debug("Extracted 'text' field from JSON: %s", result[:100])
                    elif isinstance(parsed_content, list) and len(parsed_content) > 0:
                        first_item = parsed_content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            result = first_item['text']
                            logging.debug("Extracted 'text' field from JSON list: %s", result[:100])
                        else:
                            logging.debug(
                                "No 'text' field in JSON list, using raw content as fallback: %s", raw_content[:100]
                            )
                            result = raw_content
                    else:
                        result = raw_content
                        logging.debug('Treating raw content as plain string: %s', result[:100])
                except json.JSONDecodeError:
                    result = raw_content
                    logging.debug('Raw content is not JSON, using as-is: %s', result[:100])
            elif isinstance(raw_content, dict):
                logging.debug('Raw content is dict: %s', str(raw_content)[:1000])
                if 'text' in raw_content:
                    result = raw_content['text']
                    logging.debug("Extracted 'text' field from dict: %s", result[:100])
                else:
                    logging.debug(
                        "Dictionary response lacks 'text' field, using str(raw_content) as fallback: %s",
                        str(raw_content)[:100],
                    )
                    result = str(raw_content)
            else:
                logging.error('Unexpected response format: %s', type(raw_content))
                result = f'Error: Unexpected API response format: {type(raw_content)}'

            if not isinstance(result, str):
                logging.error(
                    'Extracted content is not a string: type=%s, content=%s', type(result), str(result)[:1000]
                )
                result = f'Error: Extracted content is not a string: {type(result)}'

            logging.debug('Final result type: %s, content: %s', type(result), result[:100])

            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'generate_policy_statement',
                    'query': resource,
                    'result': result,
                }
            )
            self.save_cache()

            logging.info(
                'Completed policy statement generation in %s seconds', (datetime.now() - start_time).total_seconds()
            )
            return result
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                logging.error('OCI GenAI returned 404 for policy statement generation: %s', e)
                result = 'Error: Policy statement generation failed (404)'
            else:
                logging.error('Error calling OCI GenAI for policy statement generation: %s', e)
                result = f'Error calling OCI GenAI: {str(e)}'
            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'generate_policy_statement',
                    'query': resource,
                    'result': result,
                }
            )
            self.save_cache()
            logging.info(
                'Completed policy statement generation (error) in %s seconds',
                (datetime.now() - start_time).total_seconds(),
            )
            return result
        except Exception as e:
            logging.error('Error calling OCI GenAI for policy statement generation: %s', e)
            result = f'Error calling OCI GenAI: {str(e)}'
            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'generate_policy_statement',
                    'query': resource,
                    'result': result,
                }
            )
            self.save_cache()
            logging.info(
                'Completed policy statement generation (error) in %s seconds',
                (datetime.now() - start_time).total_seconds(),
            )
            return result

    def analyze_policy_statement(self, policy_text):  # noqa: C901
        """Call OCI GenAI to analyze an OCI IAM policy statement, using cache if available."""
        logging.debug('Analyzing policy statement: %s', policy_text)

        for entry in self.ai_result_cache:
            if entry.get('type') == 'analyze_policy_statement' and entry.get('query') == policy_text:
                logging.debug('Cache hit for policy analysis: %s', policy_text)
                return entry['result']

        start_time = datetime.now()
        logging.info('Calling OCI GenAI for policy analysis: %s', policy_text)
        try:
            chat_detail = oci.generative_ai_inference.models.ChatDetails()
            chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(model_id=self.AI_MODEL_ID)

            content = oci.generative_ai_inference.models.TextContent()
            content.text = (
                f"Analyze the following OCI IAM policy statement: '{policy_text}'. "
                'Provide a detailed explanation of its components (subject, verb, resource, conditions), its purpose, and potential use cases. '
                'Evaluate its correctness and potential issues (e.g., overly broad permissions, syntax errors). '
                'Format the response in markdown with clear sections using headers (##). '
                'Use unordered lists (- item) for components, use cases, and issues, ensuring each list item has meaningful content and no empty items. '
                "Include a 'Documentation' section with a direct link if available. "
                'Avoid empty lines in lists and ensure all content is concise and relevant.'
            )

            chat_request = oci.generative_ai_inference.models.GenericChatRequest()
            chat_request.api_format = oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC
            chat_request.messages = [oci.generative_ai_inference.models.Message(role='USER', content=[content])]
            chat_request.max_tokens = 1000
            chat_request.temperature = 1
            chat_request.top_p = 1
            chat_request.top_k = 0

            chat_detail.chat_request = chat_request
            chat_detail.compartment_id = self.COMPARTMENT_ID

            logging.debug('Sending OCI GenAI API request for policy analysis')
            response = self.client.chat(chat_detail)
            raw_content = response.data.chat_response.choices[0].message.content

            logging.debug('Raw API response type: %s, content: %s', type(raw_content), str(raw_content)[:1000])

            if isinstance(raw_content, list):
                logging.debug('Raw content is a list with length %d', len(raw_content))
                if len(raw_content) > 0:
                    first_item = raw_content[0]
                    logging.debug('First item type: %s', type(first_item))
                    if hasattr(first_item, 'text'):
                        result = first_item.text
                        logging.debug(f"Extracted 'text' attribute from first item: {policy_text} = {result[:100]}")
                    elif isinstance(first_item, dict) and 'text' in first_item:
                        result = first_item['text']
                        logging.debug("Extracted 'text' key from first dict: %s", result[:100])
                    else:
                        logging.debug(
                            "First item lacks 'text' attribute or key, using str(first_item) as fallback: %s",
                            str(first_item)[:100],
                        )
                        result = str(first_item)
                else:
                    logging.debug(
                        'List response is empty, using str(raw_content) as fallback: %s', str(raw_content)[:100]
                    )
                    result = str(raw_content)
            elif isinstance(raw_content, str):
                try:
                    parsed_content = json.loads(raw_content)
                    logging.debug(
                        'Parsed JSON content type: %s, content: %s', type(parsed_content), str(parsed_content)[:1000]
                    )
                    if isinstance(parsed_content, dict) and 'text' in parsed_content:
                        result = parsed_content['text']
                        logging.debug("Extracted 'text' field from JSON: %s", result[:100])
                    elif isinstance(parsed_content, list) and len(parsed_content) > 0:
                        first_item = parsed_content[0]
                        if isinstance(first_item, dict) and 'text' in first_item:
                            result = first_item['text']
                            logging.debug("Extracted 'text' field from JSON list: %s", result[:100])
                        else:
                            logging.debug(
                                "No 'text' field in JSON list, using raw content as fallback: %s", raw_content[:100]
                            )
                            result = raw_content
                    else:
                        result = raw_content
                        logging.debug('Treating raw content as plain string: %s', result[:100])
                except json.JSONDecodeError:
                    result = raw_content
                    logging.debug('Raw content is not JSON, using as-is: %s', result[:100])
            elif isinstance(raw_content, dict):
                logging.debug('Raw content is dict: %s', str(raw_content)[:1000])
                if 'text' in raw_content:
                    result = raw_content['text']
                    logging.debug("Extracted 'text' field from dict: %s", result[:100])
                else:
                    logging.debug(
                        "Dictionary response lacks 'text' field, using str(raw_content) as fallback: %s",
                        str(raw_content)[:100],
                    )
                    result = str(raw_content)
            else:
                logging.error('Unexpected response format: %s', type(raw_content))
                result = f'Error: Unexpected API response format: {type(raw_content)}'

            if not isinstance(result, str):
                logging.error(
                    'Extracted content is not a string: type=%s, content=%s', type(result), str(result)[:1000]
                )
                result = f'Error: Extracted content is not a string: {type(result)}'

            logging.debug('Final result type: %s, content: %s', type(result), result[:100])

            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'analyze_policy_statement',
                    'query': policy_text,
                    'result': result,
                }
            )
            self.save_cache()

            logging.info('Completed policy analysis in %s seconds', (datetime.now() - start_time).total_seconds())
            return result
        except oci.exceptions.ServiceError as e:
            if e.status == 404:
                logging.error('OCI GenAI returned 404 for policy analysis: %s', e)
                result = 'Error: Policy analysis failed (404)'
            else:
                logging.error('Error calling OCI GenAI for policy analysis: %s', e)
                result = f'Error calling OCI GenAI: {str(e)}'
            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'analyze_policy_statement',
                    'query': policy_text,
                    'result': result,
                }
            )
            self.save_cache()
            logging.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
            return result
        except Exception as e:
            logging.error('Error calling OCI GenAI for policy analysis: %s', e)
            result = f'Error calling OCI GenAI: {str(e)}'
            self.ai_result_cache.append(
                {
                    'date': datetime.now(UTC).isoformat(),
                    'type': 'analyze_policy_statement',
                    'query': policy_text,
                    'result': result,
                }
            )
            self.save_cache()
            logging.info(
                'Completed policy analysis (error) in %s seconds', (datetime.now() - start_time).total_seconds()
            )
            return result
