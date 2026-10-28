"""Corpus v2: v1 tasks with fresh held-out cases; v1 itself stays frozen.

Every v1 case (including the former held-out ones, which earlier runs were scored
and analysed on) becomes an example case here. Five new held-out cases per tool
task are added. Instructions and the first example are unchanged, so v1 prompts
remain valid and candidates generated from them can be scored on unseen cases.
Example cases may feed development and repair; held-out cases serve admission only.
"""
from copy import deepcopy

from .evaluation_corpus import get_task as _v1_task, list_tasks as _v1_tasks
from .review import _digest, _json

CORPUS_VERSION = 'toolwright-eval-v2'

_HELD_OUT = {
    'integer-sum': [
        ('single', {'values': [42]}, 42),
        ('large', {'values': [10 ** 12, 10 ** 12, -1]}, 1999999999999),
        ('zeros', {'values': [0, 0, 0]}, 0),
        ('mixed', {'values': [100, -50, 25, -75]}, 0),
        ('many-negative', {'values': [-1, -2, -3, -4]}, -10)],
    'stable-unique': [
        ('single', {'values': ['x']}, ['x']),
        ('all-same', {'values': ['q', 'q', 'q']}, ['q']),
        ('whitespace', {'values': [' a', 'a', ' a', 'a ']}, [' a', 'a', 'a ']),
        ('unicode', {'values': ['é', 'e', 'é']}, ['é', 'e']),
        ('order', {'values': ['c', 'b', 'a', 'b', 'c']}, ['c', 'b', 'a'])],
    'word-counts': [
        ('single', {'text': 'Hello'}, {'hello': 1}),
        ('case-mix', {'text': 'Go GO go gO'}, {'go': 4}),
        ('punctuation', {'text': 'end. End. end'}, {'end.': 2, 'end': 1}),
        ('multi-space', {'text': 'x  y\t\tx'}, {'x': 2, 'y': 1}),
        ('empty-string', {'text': ''}, {})],
    'group-totals': [
        ('single', {'rows': [{'group': 'x', 'amount': 7}]}, {'x': 7}),
        ('zero', {'rows': [{'group': 'z', 'amount': 0}]}, {'z': 0}),
        ('many-groups', {'rows': [{'group': 'a', 'amount': 1}, {'group': 'b', 'amount': 2},
                                  {'group': 'c', 'amount': 3}, {'group': 'a', 'amount': 4}]},
         {'a': 5, 'b': 2, 'c': 3}),
        ('cancel', {'rows': [{'group': 'a', 'amount': 5}, {'group': 'a', 'amount': -5}]}, {'a': 0}),
        ('case-sensitive', {'rows': [{'group': 'A', 'amount': 1}, {'group': 'a', 'amount': 2}]},
         {'A': 1, 'a': 2})],
    'active-ids': [
        ('none-active', {'rows': [{'id': 1, 'active': False}]}, []),
        ('all-active', {'rows': [{'id': 3, 'active': True}, {'id': 1, 'active': True},
                                 {'id': 2, 'active': True}]}, [3, 1, 2]),
        ('duplicates', {'rows': [{'id': 5, 'active': True}, {'id': 5, 'active': True}]}, [5, 5]),
        ('zero-id', {'rows': [{'id': 0, 'active': True}]}, [0]),
        ('mixed', {'rows': [{'id': 1, 'active': True}, {'id': 2, 'active': False},
                            {'id': 3, 'active': True}, {'id': 4, 'active': False}]}, [1, 3])],
    'median': [
        ('single', {'values': [7]}, 7.0),
        ('two', {'values': [1, 2]}, 1.5),
        ('negative-odd', {'values': [-5, -1, -3]}, -3.0),
        ('duplicates', {'values': [2, 2, 2, 9]}, 2.0),
        ('unsorted-even', {'values': [10, -10, 4, 6]}, 5.0)],
    'clamp-values': [
        ('inside', {'values': [1, 2, 3], 'low': 0, 'high': 5}, [1, 2, 3]),
        ('all-low', {'values': [-10, -20], 'low': -1, 'high': 1}, [-1, -1]),
        ('all-high', {'values': [100], 'low': 0, 'high': 10}, [10]),
        ('empty', {'values': [], 'low': 0, 'high': 1}, []),
        ('bounds', {'values': [0, 5], 'low': 0, 'high': 5}, [0, 5])],
    'chunk-list': [
        ('exact', {'values': [1, 2, 3, 4], 'size': 2}, [[1, 2], [3, 4]]),
        ('size-one', {'values': [1, 2, 3], 'size': 1}, [[1], [2], [3]]),
        ('equal-size', {'values': [4, 5, 6], 'size': 3}, [[4, 5, 6]]),
        ('mixed-types', {'values': ['a', None, True], 'size': 2}, [['a', None], [True]]),
        ('remainder', {'values': [1, 2, 3, 4, 5, 6, 7], 'size': 3}, [[1, 2, 3], [4, 5, 6], [7]])],
    'flatten-once': [
        ('single', {'arrays': [[1]]}, [1]),
        ('all-empty', {'arrays': [[], []]}, []),
        ('strings', {'arrays': [['a', 'b'], ['c']]}, ['a', 'b', 'c']),
        ('deep', {'arrays': [[[[1]]], [2]]}, [[[1]], 2]),
        ('objects', {'arrays': [[{'k': 1}], [{'k': 2}]]}, [{'k': 1}, {'k': 2}])],
    'dot-product': [
        ('single', {'a': [3], 'b': [4]}, 12),
        ('zeros', {'a': [0, 0], 'b': [5, 6]}, 0),
        ('large', {'a': [10 ** 9, 2], 'b': [10 ** 9, 3]}, 1000000000000000006),
        ('all-negative', {'a': [-1, -2], 'b': [-3, -4]}, 11),
        ('mixed', {'a': [1, -1, 1], 'b': [1, 1, 1]}, 1)],
    'sort-records': [
        ('single', {'rows': [{'name': 'only', 'score': 0}]}, ['only']),
        ('all-tied', {'rows': [{'name': 'c', 'score': 1}, {'name': 'a', 'score': 1},
                               {'name': 'b', 'score': 1}]}, ['a', 'b', 'c']),
        ('negative', {'rows': [{'name': 'x', 'score': -5}, {'name': 'y', 'score': -1}]}, ['y', 'x']),
        ('mixed', {'rows': [{'name': 'd', 'score': 3}, {'name': 'c', 'score': 3},
                            {'name': 'e', 'score': 10}, {'name': 'a', 'score': 1}]}, ['e', 'c', 'd', 'a']),
        ('distinct', {'rows': [{'name': 'p', 'score': 1}, {'name': 'q', 'score': 2},
                               {'name': 'r', 'score': 3}]}, ['r', 'q', 'p'])],
    'date-distance': [
        ('same', {'start': '2024-05-05', 'end': '2024-05-05'}, 0),
        ('year', {'start': '2023-01-01', 'end': '2024-01-01'}, 365),
        ('leap-year', {'start': '2024-01-01', 'end': '2025-01-01'}, 366),
        ('century', {'start': '1900-02-28', 'end': '1900-03-01'}, 1),
        ('backward-month', {'start': '2024-03-01', 'end': '2024-02-01'}, -29)],
    'csv-projection': [
        ('single-column', {'text': 'id\n1\n2\n', 'field': 'id'}, ['1', '2']),
        ('empty-field', {'text': 'a,b\nx,\n,y\n', 'field': 'b'}, ['', 'y']),
        ('no-trailing-newline', {'text': 'k,v\nq,1', 'field': 'v'}, ['1']),
        ('escaped-quote', {'text': 'name,q\nA,"say ""hi"""\n', 'field': 'q'}, ['say "hi"']),
        ('crlf', {'text': 'a,b\r\n1,2\r\n3,4\r\n', 'field': 'a'}, ['1', '3'])],
    'json-project': [
        ('all', {'object': {'a': 1, 'b': 2}, 'keys': ['a', 'b']}, {'a': 1, 'b': 2}),
        ('none-present', {'object': {'a': 1}, 'keys': ['z']}, {}),
        ('nested', {'object': {'a': {'x': [1]}, 'b': 3}, 'keys': ['a']}, {'a': {'x': [1]}}),
        ('empty-keys', {'object': {'a': 1}, 'keys': []}, {}),
        ('empty-values', {'object': {'s': '', 'l': []}, 'keys': ['s', 'l']}, {'s': '', 'l': []})],
    'run-length': [
        ('single', {'values': [5]}, [[5, 1]]),
        ('all-same', {'values': [3, 3, 3, 3]}, [[3, 4]]),
        ('alternating', {'values': [1, 2, 1, 2]}, [[1, 1], [2, 1], [1, 1], [2, 1]]),
        ('negative', {'values': [-1, -1, 0]}, [[-1, 2], [0, 1]]),
        ('zero', {'values': [0]}, [[0, 1]])],
    'balanced-parentheses': [
        ('nested', {'text': '((()))'}, True),
        ('unclosed', {'text': '(()'}, False),
        ('other-brackets', {'text': '[(])'}, True),
        ('empty-string', {'text': ''}, True),
        ('close-first', {'text': 'a)b(c'}, False)],
}


def _build():
    tasks = []
    for summary in _v1_tasks():
        task = _v1_task(summary['id'])
        if task['kind'] == 'tool':
            for case in task['cases']:
                case['split'] = 'example'
            task['cases'] += [{'id': name, 'split': 'held-out', 'args': {'data': data},
                               'expected': {'result': expected}}
                              for name, data, expected in _HELD_OUT[task['id']]]
        tasks.append(task)
    return tasks


_TASKS = _build()


def corpus_digest():
    return _digest(_json({'version': CORPUS_VERSION, 'tasks': _TASKS}))


def get_task(identifier):
    for task in _TASKS:
        if task['id'] == identifier:
            return deepcopy(task)
    raise ValueError('unknown_evaluation_task')


def list_tasks():
    return [{'id': task['id'], 'kind': task['kind'], 'cases': len(task['cases'])} for task in _TASKS]


def get_case(task_id, case_id):
    task = get_task(task_id)
    if task['kind'] != 'tool':
        raise PermissionError('evaluation_task_requires_refusal')
    for case in task['cases']:
        if case['id'] == case_id:
            return task, case
    raise ValueError('unknown_evaluation_case')


def list_cases(task_id, split=None):
    """Case identifiers and splits only, never inputs or expected answers."""
    if split not in (None, 'example', 'held-out'):
        raise ValueError('invalid_evaluation_split')
    return [{'id': case['id'], 'split': case['split']} for case in get_task(task_id)['cases']
            if split is None or case['split'] == split]
