"""Bind an in-process generation observation to a frozen evaluation prompt."""
from .contracts import json_object
from .evaluation import score_decision
from .evaluation_corpus import CORPUS_VERSION, corpus_digest, decision_prompt, generation_prompt, get_task
from .generation_results import GenerationResult, request_digest, text_digest


def record_generation(task_id, result, *, expected_corpus_sha256, mode='source'):
    """No provider call, persistence, preparation or execution; not an attestation."""
    if expected_corpus_sha256 != corpus_digest():
        raise ValueError('evaluation_corpus_mismatch')
    task = get_task(task_id)
    if mode not in ('source', 'decision'):
        raise ValueError('invalid_evaluation_generation_mode')
    if not isinstance(result, GenerationResult):
        raise ValueError('generation_result_required')
    prompt = decision_prompt(task_id) if mode == 'decision' else generation_prompt(task_id)
    if result.prompt_sha256 != text_digest(prompt) or result.response_sha256 != text_digest(result.text):
        raise ValueError('evaluation_generation_binding_mismatch')
    options = {'temperature': result.temperature, 'num_predict': result.max_tokens}
    if result.seed is not None:
        options['seed'] = result.seed
    payload = {'model': result.requested_model, 'prompt': prompt, 'stream': True, 'options': options}
    if result.json_mode:
        payload['format'] = 'json'
    if result.request_sha256 != request_digest(payload):
        raise ValueError('evaluation_generation_request_mismatch')
    kind = 'decision' if mode == 'decision' or task['kind'] == 'refusal' else 'source'
    status = 'unreviewed_source'
    if kind == 'decision':
        try:
            status = score_decision(task_id, json_object(result.text))['status']
        except ValueError:
            status = 'invalid_response'
    return {'corpus_version': CORPUS_VERSION, 'corpus_sha256': corpus_digest(), 'task_id': task_id,
            'mode': mode, 'response_kind': kind, 'status': status, 'generation': result.to_dict(),
            'generation_provenance_verified': False, 'execution_authorized': False}
