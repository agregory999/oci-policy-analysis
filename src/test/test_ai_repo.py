from types import SimpleNamespace

from oci_policy_analysis.application.core.repo.ai_repo import AI


def test_update_config_applies_inference_endpoint() -> None:
    ai = AI()
    ai.genai_inference_client = SimpleNamespace(base_client=SimpleNamespace(endpoint='old'))

    ai.update_config('model-ocid', 'https://inference.example.com/', 'compartment-ocid')

    assert ai.model_ocid == 'model-ocid'
    assert ai.compartment_ocid == 'compartment-ocid'
    assert ai.endpoint == 'https://inference.example.com/'
    assert ai.genai_inference_client.base_client.endpoint == 'https://inference.example.com'
