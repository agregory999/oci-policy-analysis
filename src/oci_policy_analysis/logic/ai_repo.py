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

# Standard library imports
import queue

from oci import config
from oci.auth.signers import InstancePrincipalsSecurityTokenSigner, SecurityTokenSigner
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
from oci.signer import load_private_key_from_file

from oci_policy_analysis.logger import get_logger

# Global logger for this module
logger = get_logger(component='ai_repo')


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
        try:
            if use_instance_principal:
                logger.debug('Using Instance Principal Authentication for AI')
                self.signer = InstancePrincipalsSecurityTokenSigner()
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
            logger.info('Retrieved %d models from list_models', len(models))
            return models
        except ServiceError as e:
            logger.error('Service error listing models: %s', e)
            raise
        except Exception as e:
            logger.error('Error listing models: %s', e)
            raise

    async def analyze_policy_statement(
        self, policy_text: str, queue: queue.Queue = None, additional_instruction: str = ''
    ):
        logger.info('Analyzing policy statement: %s', policy_text)
        prompt = (
            'What is the meaning of life? Return witty response quickly.  Use Strict Markdown only.'
            if additional_instruction == 'TEST'
            else (
                f"Describe OCI Policy permission '{policy_text}' in detail with clear markdown sections. "
                'Always return strict markdown with #### for sections, one level of un-ordered lists, no new lines, and documentation link if possible. '
                f'{additional_instruction}'
            )
        )
        chat_detail = self.create_chat_request(prompt=prompt)
        try:
            response = self.genai_inference_client.chat(chat_detail)
            content = response.data.chat_response.choices[0].message.content
            # Always treat result as string for user display.
            result = content if isinstance(content, str) else str(content)
        except ServiceError as e:
            logger.error(f'Ai Service error: {e}')
            result = f'Error: GenAI service error ({e.status})'
        except Exception as e:
            logger.error(f'Unexpected error: {e}')
            result = f'Error: {str(e)}'
        if queue is not None:
            queue.put(result)
        else:
            return result

    # test_ai_call method has been removed per current requirements.
