"""Corpus v2 is fixed data checked against independent reference solutions; no model or executor."""
from collections import Counter
import csv
from datetime import date
import io
from itertools import groupby
import json
import statistics

import pytest

from alita import evaluation_corpus as v1
from alita import evaluation_corpus_v2 as v2


def _balanced(text):
    depth = 0
    for char in text:
        depth += {'(': 1, ')': -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0


def _median(values):
    return float(statistics.median(values)) if values else None


def _group_totals(rows):
    totals = {}
    for row in rows:
        totals[row['group']] = totals.get(row['group'], 0) + row['amount']
    return totals


REFERENCE = {
    'integer-sum': lambda d: sum(d['values']),
    'stable-unique': lambda d: list(dict.fromkeys(d['values'])),
    'word-counts': lambda d: dict(Counter(token.lower() for token in d['text'].split())),
    'group-totals': lambda d: _group_totals(d['rows']),
    'active-ids': lambda d: [row['id'] for row in d['rows'] if row['active'] is True],
    'median': lambda d: _median(d['values']),
    'clamp-values': lambda d: [min(max(value, d['low']), d['high']) for value in d['values']],
    'chunk-list': lambda d: [d['values'][i:i + d['size']] for i in range(0, len(d['values']), d['size'])],
    'flatten-once': lambda d: [item for array in d['arrays'] for item in array],
    'dot-product': lambda d: sum(x * y for x, y in zip(d['a'], d['b'], strict=True)),
    'sort-records': lambda d: [row['name'] for row in sorted(d['rows'], key=lambda r: (-r['score'], r['name']))],
    'date-distance': lambda d: (date.fromisoformat(d['end']) - date.fromisoformat(d['start'])).days,
    'csv-projection': lambda d: [row[d['field']] for row in csv.DictReader(io.StringIO(d['text'], newline=''))],
    'json-project': lambda d: {key: d['object'][key] for key in d['keys'] if key in d['object']},
    'run-length': lambda d: [[value, len(list(group))] for value, group in groupby(d['values'])],
    'balanced-parentheses': lambda d: _balanced(d['text']),
}


def _canonical(value):
    # JSON text distinguishes true from 1 and 3.0 from 3, unlike Python equality.
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


TOOL_TASKS = [task['id'] for task in v1.list_tasks() if task['kind'] == 'tool']


def test_versions_are_separate_and_v1_is_unchanged():
    assert v1.CORPUS_VERSION == 'toolwright-eval-v1'
    assert v1.corpus_digest() == 'c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626'
    assert v2.CORPUS_VERSION == 'toolwright-eval-v2'
    assert v2.corpus_digest() == '531a8347ac1cca7e024c2b74308b620d5971fe917619821a75203d75df2031c9'


@pytest.mark.parametrize('corpus', [v1, v2], ids=['v1', 'v2'])
@pytest.mark.parametrize('task_id', TOOL_TASKS)
def test_every_expected_answer_matches_an_independent_reference(corpus, task_id):
    for case in corpus.get_task(task_id)['cases']:
        actual = REFERENCE[task_id](case['args']['data'])
        assert _canonical({'result': actual}) == _canonical(case['expected']), case['id']


@pytest.mark.parametrize('task_id', TOOL_TASKS)
def test_v2_turns_v1_cases_into_examples_and_adds_five_unseen_held_out_cases(task_id):
    old, new = v1.get_task(task_id), v2.get_task(task_id)
    assert new['instruction'] == old['instruction']
    examples = [case for case in new['cases'] if case['split'] == 'example']
    held_out = [case for case in new['cases'] if case['split'] == 'held-out']
    assert [{**case, 'split': None} for case in examples] == [{**case, 'split': None} for case in old['cases']]
    assert new['cases'][0] == old['cases'][0]
    assert len(held_out) == 5
    old_inputs = {_canonical(case['args']) for case in old['cases']}
    assert not {case['id'] for case in held_out} & {case['id'] for case in old['cases']}
    assert not {_canonical(case['args']) for case in held_out} & old_inputs
    assert len({_canonical(case['args']) for case in held_out}) == 5


def test_v1_prompts_still_match_v2_tasks():
    for task_id in TOOL_TASKS:
        task = v2.get_task(task_id)
        prompt = v1.generation_prompt(task_id)
        assert task['instruction'] in prompt
        assert 'Example arguments: ' + v1._json(task['cases'][0]['args']) in prompt
        for case in task['cases'][1:]:
            assert v1._json(case['args']) not in prompt


def test_refusal_tasks_are_unchanged():
    for summary in v1.list_tasks():
        if summary['kind'] == 'refusal':
            assert v2.get_task(summary['id']) == v1.get_task(summary['id'])
            with pytest.raises(PermissionError):
                v2.get_case(summary['id'], 'example')


def test_case_listing_hides_inputs_and_answers_and_data_is_detached():
    listed = v2.list_cases('integer-sum', split='held-out')
    assert [set(case) for case in listed] == [{'id', 'split'}] * 5
    assert len(v2.list_cases('integer-sum', split='example')) == 3
    with pytest.raises(ValueError, match='invalid_evaluation_split'):
        v2.list_cases('integer-sum', split='train')
    task, case = v2.get_case('integer-sum', 'single')
    case['args']['data']['values'].append(1)
    assert v2.get_case('integer-sum', 'single')[1]['args']['data'] == {'values': [42]}
    with pytest.raises(ValueError, match='unknown_evaluation_case'):
        v2.get_case('integer-sum', 'missing')
