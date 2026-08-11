########################################################################### No AI cache logic remains as per latest project requirements.

# Copyright (c) 2024, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#
# DISCLAIMER This is not an official Oracle application, It does not supported by Oracle Support.
#
# ai_repo.py
#
# @author: Andrew Gregory
#
# Supports Python 3.12 and above
#
# coding: utf-8
##########################################################################

import json
import queue
from importlib.resources import files

from oci import config
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner, SecurityTokenSigner
from oci.exceptions import ServiceError
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
from oci.identity import IdentityClient
from oci.signer import load_private_key_from_file

from oci_policy_analysis.application.core.support.logger import get_logger

# Global logger for this module
logger = get_logger(component='core.repo.ai_repo')


def load_ai_model_config() -> dict[str, object]:
    """Load the user-maintained AI model test and inference configuration."""
    try:
        resource = files('oci_policy_analysis.application.core.resources').joinpath('ai_tested_models.json')
        data = json.loads(resource.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning('Unable to load AI tested-model list: %s', exc)
        return {}


def load_tested_model_ids() -> set[str]:
    """Load the small, user-maintained set of known-working model identifiers."""
    data = load_ai_model_config()
    return {str(value).strip() for value in data.get('tested_model_ids', []) if str(value).strip()}


def load_inference_model_overrides() -> dict[str, str]:
    """Load management-OCID to inference-model-name overrides."""
    overrides = load_ai_model_config().get('inference_model_overrides', {})
    if not isinstance(overrides, dict):
        return {}
    return {str(key).strip(): str(value).strip() for key, value in overrides.items() if key and value}


class AI:
    """AI Module for OCI Policy Analysis

    Contains all of the available GenAI calls that can be made to obtain additional context.

    Attributes:
        genai_client: The OCI GenAI Client.
        genai_inference_client: The OCI GenAI Inference Client
    """

    def __init__(self):
        """Initialize OCI GenAI client and constants."""
        logger.info('Initialized AI Module')
        self.initialized = False

    def initialize_client(
        self, use_instance_principal: bool, session_token: str | None = None, profile: str = 'DEFAULT'
    ) -> bool:
        """
        Initialize OCI GenAI Client with authentication.
        Args:
            use_instance_principal (bool): Whether to use Instance Principal authentication.
            session_token (str | None): Session token profile name for authentication.
            profile (str): Profile name for authentication if not using instance principal or session token.
        Returns:
            bool: True if initialization is successful, False otherwise."""
        try:
            if use_instance_principal:
                logger.debug('Using Instance Principal Authentication for AI')
                self.signer = InstancePrincipalsSecurityTokenSigner()
                self.config = {}
                self.genai_client = GenerativeAiClient(config={}, signer=self.signer)
                self.genai_inference_client = GenerativeAiInferenceClient(config={}, signer=self.signer)
                self.tenancy_ocid = self.signer.tenancy_id
                self.region = self.signer.region
            elif session_token:
                logger.info('Attempt session auth')
                self.config = config.from_file(profile_name=session_token)
                token_file = self.config['security_token_file']
                token = None
                with open(token_file) as f:
                    token = f.read()
                private_key = load_private_key_from_file(self.config['key_file'])
                self.signer = SecurityTokenSigner(token, private_key)
                self.genai_client = GenerativeAiClient(config={'region': self.config['region']}, signer=self.signer)
                self.genai_inference_client = GenerativeAiInferenceClient(
                    config={'region': self.config['region']}, signer=self.signer
                )
                self.tenancy_ocid = self.config['tenancy']
                self.region = self.config['region']
                logger.info('Success session auth')
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
        except Exception as exc:
            logger.fatal(f'Authentication failed: {exc}')
            return False

    def update_config(self, model_ocid, endpoint, compartment_ocid):
        """
        Update Model ID and Endpoint, reinitializing client if endpoint changes.
        Args:
            model_ocid (str): The model OCID to use.
            endpoint (str): The endpoint URL to use.
            compartment_ocid (str): The compartment OCID for requests."""
        logger.info(
            f'Updating AI config: Model OCID:{model_ocid}, Endpoint:{endpoint}, Compartment: {compartment_ocid}'
        )
        self.model_ocid = model_ocid
        self.endpoint = endpoint
        self.compartment_ocid = compartment_ocid
        # The endpoint entry must affect the client used by chat(); retaining
        # it only as a setting makes tests misleading because requests continue
        # to use the endpoint selected during client initialization.
        if getattr(self, 'genai_inference_client', None) is not None and endpoint:
            self.genai_inference_client.base_client.endpoint = endpoint.rstrip('/')

    def list_subscribed_regions(self) -> list[str]:
        """Return regions subscribed by the authenticated tenancy."""
        signer = getattr(self, 'signer', None)
        if signer is not None:
            identity_client = IdentityClient(config={}, signer=signer)
        elif getattr(self, 'config', None):
            identity_client = IdentityClient(getattr(self, 'config', {}))
        else:
            raise RuntimeError('AI authentication is not initialized')
        response = identity_client.list_region_subscriptions(self.tenancy_ocid)
        return sorted(region.region_name for region in (response.data or []) if getattr(region, 'region_name', None))

    def set_region(self, region: str) -> None:
        """Point management and inference clients at a subscribed region."""
        region = region.strip()
        if not region:
            raise ValueError('Region cannot be empty')
        self.region = region
        self.base_endpoint = f'https://inference.generativeai.{region}.oci.oraclecloud.com'
        self.genai_client.base_client.endpoint = f'https://generativeai.{region}.oci.oraclecloud.com'
        self.genai_inference_client.base_client.endpoint = self.base_endpoint

    def _create_chat_request(self, prompt) -> ChatDetails:
        """Create a Chat Request for the given prompt.
        Args:
            prompt (str): The prompt to send to the AI model.
        Returns:
            ChatDetails: The constructed chat request details.
        """
        chat_detail = ChatDetails()
        chat_detail.serving_mode = OnDemandServingMode(model_id=self.model_ocid)

        content = TextContent()
        content.text = prompt

        chat_request = GenericChatRequest()
        chat_request.api_format = BaseChatRequest.API_FORMAT_GENERIC
        chat_request.messages = [Message(role='USER', content=[content])]
        # chat_request.max_tokens = 1500
        chat_request.temperature = 0
        chat_request.top_p = 0.25
        # chat_request.top_k = 0

        # TODO: Change the parameters above based on chosen model.  Need to test with multiple models to determine best defaults and if any parameters should be locked to specific values for certain models.

        chat_detail.chat_request = chat_request
        chat_detail.compartment_id = self.compartment_ocid
        logger.info(f'Created Chat Request with prompt: {prompt}')
        logger.debug(f'Created Chat: {chat_detail}')
        return chat_detail

    def list_models(self) -> list[dict]:
        """
        List available models using GenerativeAiClient.list_models.
        Returns:
            list[dict]: A list of available GenAI models with their details.
        """
        logger.info('Listing available models')
        try:
            # Try to list models from tenancy
            response = self.genai_client.list_models(compartment_id=self.tenancy_ocid)
            if (
                response is None
                or getattr(response, 'data', None) is None
                or getattr(response.data, 'items', None) is None
            ):
                logger.error('list_models response or response.data or response.data.items is None')
                return []
            models = [
                {
                    'Model Name': model.display_name or 'Unknown',
                    'Model OCID': model.id,
                    'Capabilities': ', '.join(model.capabilities) if model.capabilities else 'N/A',
                    'Lifecycle State': model.lifecycle_state or 'N/A',
                    'Creation Date': model.time_created.isoformat() if model.time_created else 'N/A',
                }
                for model in response.data.items
                if 'CHAT' in (model.capabilities or [])
            ]
            logger.info('Retrieved %d models from list_models', len(models))
            return models
        except ServiceError as e:
            logger.error('Service error listing models: %s', e)
            raise
        except Exception as e:
            logger.error('Error listing models: %s', e)
            raise

    async def analyze_policy_statement(
        self,
        policy_text: str,
        format: str = 'Markdown',
        queue: queue.Queue | None = None,
        additional_instruction: str = '',
    ):
        """
        Analyze a policy statement using the GenAI Inference Client.

        Args:
            policy_text (str): The policy statement text to analyze.
            format (str): The result format to use. "Markdown" means the GenAI should return markdown, "Text" means plain text using newlines for paragraphs and no bullet points, no markdown, no HTML.
            queue (queue.Queue|None): Optional queue to put the result into for async calls.
            additional_instruction (str): Additional instructions to include in the prompt.
        Returns:
            str: The analysis result from the AI model.
        """
        logger.info(f'Analyzing policy statement: {policy_text} (Format={format})')
        if additional_instruction == 'TEST':
            if format.upper() == 'TEXT':
                prompt = 'What is the meaning of life? Return witty response quickly, in plain text only, no markdown, no bullets, no lists, newlines as paragraph markers.'
            else:
                prompt = 'What is the meaning of life? Return witty response quickly.  Use Strict Markdown only.'
        else:
            if format.upper() == 'TEXT':
                prompt = (
                    f"Describe OCI Policy permission '{policy_text}' in detail using only plain text with clear, well-separated paragraphs. "
                    'Do not use any markdown, bullet points, lists, HTML, or formatting: just pure readable text, and use blank lines (double newlines) for paragraph breaks. '
                    'If you include any reference link, write the full https://... on its own line. '
                    f'{additional_instruction}'
                )
            else:
                prompt = (
                    f"Describe OCI Policy permission '{policy_text}' in detail with clear markdown sections. "
                    'Always return strict markdown with #### for sections, one level of un-ordered lists, no new lines except for semantic breaks, and documentation link if possible. '
                    f'{additional_instruction}'
                )
        chat_detail = self._create_chat_request(prompt=prompt)
        try:
            response = self.genai_inference_client.chat(chat_detail)
            if (
                response is not None
                and getattr(response, 'data', None) is not None
                and getattr(response.data, 'chat_response', None) is not None
                and getattr(response.data.chat_response, 'choices', None)
                and len(response.data.chat_response.choices) > 0
                and getattr(response.data.chat_response.choices[0], 'message', None) is not None
                and getattr(response.data.chat_response.choices[0].message, 'content', None) is not None
            ):
                content = response.data.chat_response.choices[0].message.content
                # Always treat result as string for user display.
                result = content if isinstance(content, str) else str(content)
            else:
                logger.error('AI chat response was None or incomplete (missing required attributes)')
                result = 'Error: GenAI response incomplete; enable detailed logging for diagnostics'
        except ServiceError as e:
            logger.error(
                'AI service error: model=%s endpoint=%s status=%s: %s', self.model_ocid, self.endpoint, e.status, e
            )
            result = f'Error: GenAI service returned HTTP {e.status}; enable detailed logging for diagnostics'
        except Exception as e:
            logger.error('Unexpected AI error: model=%s endpoint=%s', self.model_ocid, self.endpoint, exc_info=True)
            result = f'Error: GenAI request failed ({type(e).__name__}); enable detailed logging for diagnostics'
        if queue is not None:
            queue.put(result)
        else:
            return result

    # test_ai_call method has been removed per current requirements.
