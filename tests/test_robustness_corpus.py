"""The additive robustness probes are fixed data, not model or executor tests."""
import pytest

from alita.evaluation_corpus import corpus_digest
from alita.robustness_corpus import (ROBUSTNESS_VERSION, get_robustness_case,
                                     list_robustness_cases, robustness_digest)


def test_robustness_corpus_is_versioned_and_separate_from_frozen_eval():
    assert ROBUSTNESS_VERSION == 'toolwright-robustness-v1'
    assert robustness_digest() == 'b4f34205f9a67bdda2c50aaf31910a5f844de71d55b85a9e65c8ff4d1d511fa5'
    assert corpus_digest() == 'c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626'
    cases = list_robustness_cases()
    assert len(cases) == 11
    assert sum(case['class'] == 'valid' for case in cases) == 4
    assert sum(case['class'] == 'invalid' for case in cases) == 7


def test_invalid_input_cases_require_a_clean_rejection_contract():
    for summary in list_robustness_cases():
        case = get_robustness_case(summary['id'])
        if case['class'] == 'invalid':
            assert case['expected'] == {
                'returncode': 'nonzero', 'stdout': 'empty',
                'stderr': 'fixed_nonempty_no_traceback',
            }
        else:
            assert set(case['expected']) == {'result'}


def test_case_data_is_detached_and_unknown_cases_fail():
    case = get_robustness_case('empty-values')
    case['data']['values'].append(9)
    assert get_robustness_case('empty-values')['data'] == {'values': []}
    with pytest.raises(ValueError, match='unknown_robustness_case'):
        get_robustness_case('unknown')
