"""Versioned input-boundary probes, separate from the frozen task corpus."""
from copy import deepcopy

from .review import _digest, _json

ROBUSTNESS_VERSION = 'toolwright-robustness-v1'


_CASES = [
    {'id': 'empty-values', 'class': 'valid', 'data': {'values': []},
     'expected': {'result': 0}},
    {'id': 'negative-cancellation', 'class': 'valid', 'data': {'values': [-7, 4, -2]},
     'expected': {'result': -5}},
    {'id': 'large-exact-integer', 'class': 'valid',
     'data': {'values': [9007199254740993, 7]},
     'expected': {'result': 9007199254741000}},
    {'id': 'many-values', 'class': 'valid', 'data': {'values': [1] * 2000},
     'expected': {'result': 2000}},
    {'id': 'missing-values', 'class': 'invalid', 'data': {},
     'expected': {'returncode': 'nonzero', 'stdout': 'empty', 'stderr': 'fixed_nonempty_no_traceback'}},
    {'id': 'extra-field', 'class': 'invalid', 'data': {'values': [1], 'debug': True},
     'expected': {'returncode': 'nonzero', 'stdout': 'empty', 'stderr': 'fixed_nonempty_no_traceback'}},
    {'id': 'boolean-member', 'class': 'invalid', 'data': {'values': [1, True]},
     'expected': {'returncode': 'nonzero', 'stdout': 'empty', 'stderr': 'fixed_nonempty_no_traceback'}},
    {'id': 'float-member', 'class': 'invalid', 'data': {'values': [1, 2.5]},
     'expected': {'returncode': 'nonzero', 'stdout': 'empty', 'stderr': 'fixed_nonempty_no_traceback'}},
    {'id': 'null-values', 'class': 'invalid', 'data': {'values': None},
     'expected': {'returncode': 'nonzero', 'stdout': 'empty', 'stderr': 'fixed_nonempty_no_traceback'}},
    {'id': 'string-values', 'class': 'invalid', 'data': {'values': '12'},
     'expected': {'returncode': 'nonzero', 'stdout': 'empty', 'stderr': 'fixed_nonempty_no_traceback'}},
    {'id': 'non-object-data', 'class': 'invalid', 'data': [1, 2],
     'expected': {'returncode': 'nonzero', 'stdout': 'empty', 'stderr': 'fixed_nonempty_no_traceback'}},
]


def robustness_digest():
    return _digest(_json({'version': ROBUSTNESS_VERSION, 'task_id': 'integer-sum', 'cases': _CASES}))


def list_robustness_cases():
    return [{'id': case['id'], 'class': case['class']} for case in _CASES]


def get_robustness_case(case_id):
    for case in _CASES:
        if case['id'] == case_id:
            return deepcopy(case)
    raise ValueError('unknown_robustness_case')
