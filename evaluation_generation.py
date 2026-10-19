"""Bind an in-process generation observation to a frozen evaluation prompt."""
import warnings

from .contracts import ModelContractError, bounded_text, json_object
from .evaluation import score_decision
from .evaluation_corpus import CORPUS_VERSION, corpus_digest, get_task
from .evaluation_prompts import evaluation_prompt
from .generation_results import GenerationResult, request_digest, text_digest


def _source_check(text):
    """Reject malformed source without normalization, execution or approval."""
    try:
        bounded_text(text, 128 * 1024)
    except ModelContractError as error:
        return {'syntax_valid': None, 'reason': error.code}
    if text.lstrip().startswith(('```', '~~~')):
        return {'syntax_valid': None, 'reason': 'markdown_fence'}
    if text.rstrip().splitlines()[-1].lstrip().startswith('REQUIREMENTS:'):
        return {'syntax_valid': None, 'reason': 'requirements_marker'}
    try:
        # Compilation checks syntax only; never execute the resulting code object.
        # Suppress warnings that can include excerpts of private provider output.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            compile(text, '<evaluation source>', 'exec', dont_inherit=True)
    except (SyntaxError, ValueError, RecursionError, OverflowError):
        return {'syntax_valid': False, 'reason': 'invalid_python_syntax'}
    return {'syntax_valid': True, 'reason': None}


def record_generation(task_id, result, *, expected_corpus_sha256, mode='source', prompt_version='v1'):
    """No provider call, persistence, preparation or execution; not an attestation."""
    if expected_corpus_sha256 != corpus_digest():
        raise ValueError('evaluation_corpus_mismatch')
    task = get_task(task_id)
    if mode not in ('source', 'decision'):
        raise ValueError('invalid_evaluation_generation_mode')
    if not isinstance(result, GenerationResult):
        raise ValueError('generation_result_required')
    prompt = evaluation_prompt(task_id, mode=mode, version=prompt_version)
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
    source_check = None
    if kind == 'decision':
        try:
            status = score_decision(task_id, json_object(result.text))['status']
        except ValueError:
            status = 'invalid_response'
    elif prompt_version in ('v2', 'v3'):
        source_check = _source_check(result.text)
        if source_check['reason'] is not None:
            status = 'invalid_source'
    return {'corpus_version': CORPUS_VERSION, 'corpus_sha256': corpus_digest(), 'task_id': task_id,
            'mode': mode, 'response_kind': kind, 'status': status, 'generation': result.to_dict(),
            'prompt_version': prompt_version, 'source_check': source_check,
            'generation_provenance_verified': False, 'execution_authorized': False}
