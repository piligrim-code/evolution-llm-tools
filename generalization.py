"""Skill generalization groundwork: one documented, parameterized tool for a family of tasks.

Step A of the adaptive-skills roadmap. A family is two to four member tasks
(corpus v2 tasks or user tasks) whose example cases share one contract
signature. A generalization prompt shows each member's instruction and example
cases only, and asks for one tool that receives ``{"data": ..., "options": ...}``,
where the options select the member's behaviour. The reply is one ```python
block whose top-level ``TOOLWRIGHT_DOC`` literal documents the tool: name,
description, options and the option values (binding) for every member. The
literal is read with ``ast.literal_eval``; nothing is executed.

Evidence: `BoundMember` presents one member task with its binding as a task
source, so the generalized candidate goes through the ordinary review, single-use
execution and evidence-gated admission on that member's example and held-out
cases. It reports the member's own digest, so every attempt spends a slot of the
member's held-out budget instead of opening a fresh one. The generalization is
admitted only if one identical candidate is admitted on every member.

Nothing here approves or executes; `generate_generalization` is the only function
that contacts a model, and only when called explicitly.
"""
import ast
from copy import deepcopy
import re

from . import evaluation_corpus_v2
from .contracts import ModelContractError, bounded_text
from .evaluation_generation import _python_fence_body, _source_check
from .evaluation_prompts import _FENCE_FORMAT_RULE, _V7_BOILERPLATE_RULE
from .generation_results import GenerationResult, request_digest, text_digest
from .review import _digest, _json
from .skill_index import contract_signature, similarity
from .user_tasks import UserTaskSource

GENERALIZATION_VERSION = 'toolwright-generalization-v1'
PROMPT_VERSION = 'general-v1'
_KEY = re.compile(r'[a-z][a-z0-9_]{0,31}')
_NAME = re.compile(r'[a-z][a-z0-9_]{2,47}')
_OPTION_TYPES = {'string': str, 'integer': int, 'number': (int, float), 'boolean': bool}


class GeneralizationError(ValueError):
    pass


class Member:
    """One member task of a family: a key used in prompts and bindings, a task, its source."""

    def __init__(self, key, task_id, source=None):
        if type(key) is not str or not _KEY.fullmatch(key):
            raise GeneralizationError('invalid_member_key')
        if source is not None and not isinstance(source, UserTaskSource):
            raise GeneralizationError('member_source_must_be_corpus_v2_or_user_task')
        self.key, self.task_id = key, task_id
        self.source = evaluation_corpus_v2 if source is None else source
        task = self.source.get_task(task_id)
        if task['kind'] != 'tool':
            raise GeneralizationError('member_requires_tool_task')
        self._task = task

    @property
    def task(self):
        return deepcopy(self._task)

    def examples(self):
        return [case for case in self._task['cases'] if case['split'] == 'example']

    def held_out_inputs(self):
        return [_json(case['args']['data']) for case in self._task['cases'] if case['split'] == 'held-out']

    def signature(self):
        signatures = {contract_signature(case['args'], case['expected']) for case in self.examples()}
        if len(signatures) != 1:
            raise GeneralizationError('member_examples_have_different_contracts')
        return signatures.pop()

    def identity(self):
        return {'key': self.key, 'task_id': self.task_id, 'corpus_version': self.source.CORPUS_VERSION,
                'corpus_sha256': self.source.corpus_digest()}


def find_families(members):
    """Group members by contract signature; each group of two or more is a candidate family.

    A family is only a proposal for a human to consider. Members are ordered by key,
    and pairwise instruction similarity is reported to explain the grouping. Members
    whose examples do not share one signature are listed under `skipped` with the reason.
    """
    groups, skipped = {}, []
    for member in members:
        try:
            groups.setdefault(member.signature(), []).append(member)
        except (GeneralizationError, ValueError) as error:
            skipped.append({'member': member.key, 'reason': str(error)})
    families = []
    for signature, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda m: m.key)
        pairs = [{'members': [a.key, b.key], 'similarity': round(similarity(a._task['instruction'],
                                                                             b._task['instruction']), 3)}
                 for i, a in enumerate(group) for b in group[i + 1:]]
        families.append({'signature': signature, 'members': [m.key for m in group], 'similarity': pairs})
    return {'families': families, 'skipped': sorted(skipped, key=lambda s: s['member'])}


def _checked_family(members):
    if type(members) is not list or not 2 <= len(members) <= 4 or not all(isinstance(m, Member) for m in members):
        raise GeneralizationError('family_requires_two_to_four_members')
    if len({m.key for m in members}) != len(members):
        raise GeneralizationError('duplicate_member_key')
    if len({(m.source.corpus_digest(), m.task_id) for m in members}) != len(members):
        raise GeneralizationError('duplicate_member_task')
    if len({m.signature() for m in members}) != 1:
        raise GeneralizationError('family_members_have_different_contracts')
    return sorted(members, key=lambda m: m.key)


def generalization_prompt(members):
    """Deterministic prompt from every member's instruction and EXAMPLE cases; refuses held-out leaks."""
    members = _checked_family(members)
    lines = [f'Toolwright generalization prompt {PROMPT_VERSION}. Do not execute any code.',
             'Profile: Python standard library only; no network, host files, pip or approval bypass.',
             f'Write ONE tool that solves all {len(members)} task variants below. They share one input and '
             'output contract and differ in behaviour that options select.']
    for member in members:
        lines.append(f'Variant {member.key}: {member._task["instruction"]}')
        lines.append(f'Examples for {member.key} (data -> expected object):')
        lines += [f"{_json(case['args']['data'])} -> {_json(case['expected'])}" for case in member.examples()]
    lines += [
        'Invocation is the argv vector ["python", "tool.py", "--json", "<JSON object>"], not a shell command.',
        'Parse args = json.loads(sys.argv[2]). args has exactly two keys: "data" (as in the examples) and '
        '"options" (an object with exactly the options you declare). Validate both before computing.',
        'Reject missing, extra, or wrong-type values without coercion. For integer fields require type(value) is int; '
        'bool is not an integer.',
        'For invalid input, write one fixed short message to stderr and exit nonzero. Do not emit a traceback or stdout.',
        'For valid input, write exactly one JSON object {"result": <answer>} to stdout and no other text.',
        'Document the tool in tool.py with one top-level assignment of a literal (no expressions, no calls): '
        'TOOLWRIGHT_DOC = {"name": "<lowercase_name>", "description": "<what it does>", '
        '"options": [{"name": "<option>", "type": "string|integer|number|boolean", "description": "<meaning>"}], '
        '"bindings": {"<variant>": {"<option>": <value>}}}. '
        f'bindings must have exactly the variants {", ".join(m.key for m in members)}, each giving a value for '
        'every option.',
        'Do not hardcode the examples; follow each variant for all valid inputs.',
        _V7_BOILERPLATE_RULE,
        _FENCE_FORMAT_RULE,
    ]
    prompt = '\n'.join(lines)
    for member in members:
        for held in member.held_out_inputs():
            if held in prompt:
                raise PermissionError('generalization_prompt_contains_held_out_input')
    return prompt


def _doc_literal(source):
    """The TOOLWRIGHT_DOC literal, read without executing anything."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        raise GeneralizationError('invalid_python_syntax') from None
    found = [node for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1
             and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'TOOLWRIGHT_DOC']
    if len(found) != 1:
        raise GeneralizationError('expected_one_toolwright_doc')
    try:
        return ast.literal_eval(found[0].value)
    except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
        raise GeneralizationError('toolwright_doc_must_be_a_literal') from None


def checked_documentation(doc, keys):
    """Validate the documentation of a generalized tool against its member keys (principle 4)."""
    keys = sorted(keys)
    if type(doc) is not dict or set(doc) != {'name', 'description', 'options', 'bindings'}:
        raise GeneralizationError('doc_requires_name_description_options_bindings')
    if type(doc['name']) is not str or not _NAME.fullmatch(doc['name']):
        raise GeneralizationError('invalid_doc_name')
    try:
        description = bounded_text(doc['description'], 2000)
    except ModelContractError:
        raise GeneralizationError('invalid_doc_description') from None
    options = doc['options']
    if type(options) is not list or not 1 <= len(options) <= 8:
        raise GeneralizationError('doc_requires_one_to_eight_options')
    declared = {}
    for option in options:
        if (type(option) is not dict or set(option) != {'name', 'type', 'description'}
                or type(option['name']) is not str or not _KEY.fullmatch(option['name'])
                or option['type'] not in _OPTION_TYPES or option['name'] in declared):
            raise GeneralizationError('invalid_doc_option')
        try:
            bounded_text(option['description'], 500)
        except ModelContractError:
            raise GeneralizationError('invalid_doc_option') from None
        declared[option['name']] = option['type']
    bindings = doc['bindings']
    if type(bindings) is not dict or sorted(bindings) != keys:
        raise GeneralizationError('doc_bindings_must_cover_exactly_the_members')
    for values in bindings.values():
        if type(values) is not dict or set(values) != set(declared):
            raise GeneralizationError('binding_requires_every_option')
        for name, value in values.items():
            kind = declared[name]
            if type(value) is bool and kind != 'boolean' or not isinstance(value, _OPTION_TYPES[kind]):
                raise GeneralizationError('binding_value_has_wrong_type')
    if len({_json(values) for values in bindings.values()}) != len(bindings):
        raise GeneralizationError('bindings_must_distinguish_members')
    return {'name': doc['name'], 'description': description,
            'options': [dict(option) for option in options], 'bindings': deepcopy(bindings)}


def record_generalization(members, result):
    """Bind a reply to the exact prompt; return (record, source or None). No execution or approval."""
    members = _checked_family(members)
    if not isinstance(result, GenerationResult):
        raise ValueError('generation_result_required')
    prompt = generalization_prompt(members)
    if result.prompt_sha256 != text_digest(prompt) or result.response_sha256 != text_digest(result.text):
        raise ValueError('generalization_binding_mismatch')
    if result.json_mode is not False:
        raise ValueError('generalization_requires_fenced_source_without_json_mode')
    options = {'temperature': result.temperature, 'num_predict': result.max_tokens}
    if result.seed is not None:
        options['seed'] = result.seed
    payload = {'model': result.requested_model, 'prompt': prompt, 'stream': True, 'options': options}
    if result.think is not None:
        payload['think'] = result.think
    if result.request_sha256 != request_digest(payload):
        raise ValueError('generalization_request_mismatch')
    documentation = None
    try:
        source = _python_fence_body(result.text)
        check = _source_check(source)
    except ModelContractError as error:
        source, check = None, {'syntax_valid': None, 'reason': error.code}
    if check['reason'] is None:
        try:
            documentation = checked_documentation(_doc_literal(source), [m.key for m in members])
        except GeneralizationError as error:
            check = {**check, 'reason': str(error)}
    if check['reason'] is not None:
        source, documentation = None, None
    record = {'format': GENERALIZATION_VERSION, 'prompt_version': PROMPT_VERSION,
              'members': [m.identity() for m in members], 'signature': members[0].signature(),
              'status': 'unreviewed_source' if source is not None else 'invalid_source',
              'source_check': check, 'documentation': documentation, 'generation': result.to_dict(),
              'generation_provenance_verified': False, 'execution_authorized': False}
    return record, source


def generate_generalization(members, client, *, temperature=0, max_tokens=4096, seed=None, think=None):
    """Explicitly ask a model for one generalized candidate. Returns (record, source or None); never runs it."""
    result = client.generate_result(generalization_prompt(members), temperature=temperature, max_tokens=max_tokens,
                                    seed=seed, json_mode=False, think=think)
    return record_generalization(members, result)


class BoundMember:
    """Task-source view of one member under a generalization's binding, for ordinary admission.

    Case inputs become ``{"data": <member data>, "options": <member binding>}``; expected
    results are unchanged. `corpus_digest()` is the MEMBER's digest, so admission
    attempts with the generalized candidate spend the member's held-out budget.
    """
    CORPUS_VERSION = GENERALIZATION_VERSION

    def __init__(self, member, documentation):
        if not isinstance(member, Member):
            raise GeneralizationError('bound_member_requires_member')
        bindings = documentation.get('bindings') if isinstance(documentation, dict) else None
        if not isinstance(bindings, dict) or member.key not in bindings:
            raise GeneralizationError('documentation_has_no_binding_for_member')
        documentation = checked_documentation(documentation, list(bindings))
        self.member, self.documentation = member, documentation
        binding = documentation['bindings'][member.key]
        task = member.task
        for case in task['cases']:
            case['args'] = {'data': case['args']['data'], 'options': deepcopy(binding)}
        self._task = task
        self._spec = {'name': 'general_' + documentation['name'], 'description': documentation['description'],
                      'args': [{'name': 'data', 'type': 'object'}, {'name': 'options', 'type': 'object'}]}

    @property
    def task_id(self):
        return self.member.task_id

    def corpus_digest(self):
        return self.member.source.corpus_digest()

    def get_task(self, identifier):
        if identifier != self.member.task_id:
            raise ValueError('unknown_evaluation_task')
        return deepcopy(self._task)

    def get_case(self, task_id, case_id):
        task = self.get_task(task_id)
        for case in task['cases']:
            if case['id'] == case_id:
                return task, case
        raise ValueError('unknown_evaluation_case')

    def task_spec(self, task):
        return deepcopy(self._spec)

    def list_cases(self, split=None):
        if split not in (None, 'example', 'held-out'):
            raise ValueError('invalid_evaluation_split')
        return [{'id': case['id'], 'split': case['split']} for case in self._task['cases']
                if split is None or case['split'] == split]


def family_decision(summaries, members):
    """Admitted for the family only if one identical candidate was admitted on every member."""
    members = _checked_family(members)
    if type(summaries) is not dict or sorted(summaries) != sorted(m.key for m in members):
        raise GeneralizationError('family_decision_requires_every_member')
    candidates = {summary.get('candidate_sha256') for summary in summaries.values()}
    if len(candidates) != 1 or None in candidates:
        raise GeneralizationError('family_decision_requires_one_candidate')
    admitted = all(summary.get('admitted') is True for summary in summaries.values())
    return {'format': GENERALIZATION_VERSION, 'admitted': admitted, 'candidate_sha256': candidates.pop(),
            'members': {key: {'admitted': summaries[key]['admitted'], 'attempt': summaries[key]['attempt'],
                              'held_out_passed': summaries[key]['held_out_passed'],
                              'held_out_total': summaries[key]['held_out_total']}
                        for key in sorted(summaries)},
            'held_out_details_included': False, 'execution_authorized': False}
