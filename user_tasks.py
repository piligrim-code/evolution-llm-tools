"""User-defined tasks with their own example and held-out cases.

A person writes a task file: an instruction, example cases that the model may see,
and held-out cases that it must never see. The file becomes a task source with the
same interface as the evaluation corpus, so the normal proposal, review, execution
and evidence-gated admission flow applies to it unchanged. Generation prompts are
built from examples only and are refused if any held-out input appears in them.
Nothing here approves or executes code; `generate_user_candidate` is the only
function that contacts a model, and only when called explicitly.
"""
from copy import deepcopy
import re

from .contracts import ModelContractError, bounded_text, json_object
from .evaluation_generation import _python_fence_body, _source_check
from .evaluation_prompts import source_rules
from .generation_results import GenerationResult, request_digest, text_digest
from .review import _digest, _json

TASK_FORMAT = 'toolwright-user-task-v1'
PROMPT_VERSION = 'user-v1'
TASK_LIMIT = 256 * 1024
_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,47}')


class UserTaskError(ValueError):
    pass


def _cases(entries, split, limits):
    if type(entries) is not list or not limits[0] <= len(entries) <= limits[1]:
        raise UserTaskError(f"{split.replace('-', '_')}_case_count_must_be_{limits[0]}_to_{limits[1]}")
    cases = []
    for entry in entries:
        if type(entry) is not dict or set(entry) != {'id', 'data', 'result'}:
            raise UserTaskError('case_requires_exactly_id_data_result')
        if type(entry['id']) is not str or not _ID.fullmatch(entry['id']):
            raise UserTaskError('invalid_case_id')
        if type(entry['data']) is not dict:
            raise UserTaskError('case_data_must_be_object')
        cases.append({'id': entry['id'], 'split': split, 'args': {'data': entry['data']},
                      'expected': {'result': entry['result']}})
    return cases


class UserTaskSource:
    """Task-source interface (as in evaluation_corpus_v2) for one user task."""
    CORPUS_VERSION = TASK_FORMAT

    def __init__(self, document):
        if type(document) is not dict or set(document) != {'format', 'id', 'instruction', 'examples', 'held_out'}:
            raise UserTaskError('task_requires_format_id_instruction_examples_held_out')
        if document['format'] != TASK_FORMAT:
            raise UserTaskError('unsupported_task_format')
        if type(document['id']) is not str or not _ID.fullmatch(document['id']):
            raise UserTaskError('invalid_task_id')
        try:
            instruction = bounded_text(document['instruction'], 4000)
        except ModelContractError:
            raise UserTaskError('invalid_instruction') from None
        examples = _cases(document['examples'], 'example', (1, 10))
        held_out = _cases(document['held_out'], 'held-out', (3, 20))
        cases = examples + held_out
        if len({case['id'] for case in cases}) != len(cases):
            raise UserTaskError('duplicate_case_id')
        example_inputs = {_json(case['args']) for case in examples}
        held_inputs = [_json(case['args']) for case in held_out]
        if len(set(held_inputs)) != len(held_inputs) or example_inputs & set(held_inputs):
            raise UserTaskError('held_out_inputs_must_be_distinct_and_unseen')
        self._task = {'id': document['id'], 'kind': 'tool', 'instruction': instruction, 'cases': cases}
        self._digest = _digest(_json({'version': TASK_FORMAT, 'task': self._task}))

    @classmethod
    def from_text(cls, text):
        try:
            return cls(json_object(text, limit=TASK_LIMIT))
        except ModelContractError:
            raise UserTaskError('task_file_must_be_one_json_object') from None

    @property
    def task_id(self):
        return self._task['id']

    def corpus_digest(self):
        return self._digest

    def get_task(self, identifier):
        if identifier != self._task['id']:
            raise ValueError('unknown_evaluation_task')
        return deepcopy(self._task)

    def get_case(self, task_id, case_id):
        task = self.get_task(task_id)
        for case in task['cases']:
            if case['id'] == case_id:
                return task, case
        raise ValueError('unknown_evaluation_case')

    @staticmethod
    def task_spec(task):
        return {'name': 'task_' + task['id'].replace('-', '_'), 'description': task['instruction'],
                'args': [{'name': 'data', 'type': 'object'}]}

    def list_cases(self, split=None):
        """IDs and splits only, never inputs or expected answers."""
        if split not in (None, 'example', 'held-out'):
            raise UserTaskError('invalid_split')
        return [{'id': case['id'], 'split': case['split']} for case in self._task['cases']
                if split is None or case['split'] == split]

    def summary(self):
        return {'format': TASK_FORMAT, 'task_id': self.task_id, 'task_sha256': self._digest,
                'examples': len(self.list_cases('example')), 'held_out': len(self.list_cases('held-out')),
                'content_included': False}


def user_prompt(source):
    """Generation prompt from the instruction and example cases only."""
    task = source.get_task(source.task_id)
    lines = [f'Toolwright user task prompt {PROMPT_VERSION}. Do not execute any code.',
             'Profile: Python standard library only; no network, host files, pip or approval bypass.',
             task['instruction'],
             'A tool receives JSON arguments via --json (sys.argv[2]); data is the required object.',
             'Print one JSON object with key result. Do not hardcode the examples; follow the task for all valid inputs.',
             'Examples (arguments -> expected object):']
    lines += [f"{_json(case['args'])} -> {_json(case['expected'])}"
              for case in task['cases'] if case['split'] == 'example']
    lines += source_rules('v7')
    prompt = '\n'.join(lines)
    for case in task['cases']:
        if case['split'] == 'held-out' and _json(case['args']) in prompt:
            raise PermissionError('user_prompt_contains_held_out_input')
    return prompt


def record_user_generation(source, result):
    """Bind a reply to the exact user prompt; return (record, source text or None)."""
    if not isinstance(result, GenerationResult):
        raise ValueError('generation_result_required')
    prompt = user_prompt(source)
    if result.prompt_sha256 != text_digest(prompt) or result.response_sha256 != text_digest(result.text):
        raise ValueError('user_generation_binding_mismatch')
    if result.json_mode is not False:
        raise ValueError('user_generation_requires_fenced_source_without_json_mode')
    options = {'temperature': result.temperature, 'num_predict': result.max_tokens}
    if result.seed is not None:
        options['seed'] = result.seed
    payload = {'model': result.requested_model, 'prompt': prompt, 'stream': True, 'options': options}
    if result.think is not None:
        payload['think'] = result.think
    if result.request_sha256 != request_digest(payload):
        raise ValueError('user_generation_request_mismatch')
    try:
        text = _python_fence_body(result.text)
        check = _source_check(text)
    except ModelContractError as error:
        text, check = None, {'syntax_valid': None, 'reason': error.code}
    if check['reason'] is not None:
        text = None
    record = {'format': TASK_FORMAT, 'prompt_version': PROMPT_VERSION, 'task_id': source.task_id,
              'task_sha256': source.corpus_digest(),
              'status': 'unreviewed_source' if text is not None else 'invalid_source',
              'source_check': check, 'generation': result.to_dict(),
              'generation_provenance_verified': False, 'execution_authorized': False}
    return record, text


def generate_user_candidate(source, client, *, temperature=0, max_tokens=2048, seed=None, think=None):
    """Explicitly ask a model for one candidate. Returns (record, source text or None); never runs it."""
    result = client.generate_result(user_prompt(source), temperature=temperature, max_tokens=max_tokens,
                                    seed=seed, json_mode=False, think=think)
    return record_user_generation(source, result)
