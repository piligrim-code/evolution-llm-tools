"""Reuse-or-generate groundwork: find catalog versions by contract, decide explainably.

A version's contract signature is its input field names with coarse JSON types
plus the coarse result type. Retrieval requires an exact signature match and ranks
by word overlap with the version's description, so every decision can be explained
in one line. A match is verified on the requester's example through a normal
pending proposal before reuse. Nothing here generates, approves or executes.
"""
import re

from .catalog import CatalogError, VersionCatalog

_WORD = re.compile(r'[a-z0-9]+')
# Estimated work per path, in reviewed single-use executions and model requests.
# Generation counts one request plus the 8 admission cases of a corpus task.
COST = {'verify_reuse': {'model_requests': 0, 'executions': 1},
        'generate': {'model_requests': 1, 'executions': 8}}


def coarse_type(value):
    """Top-level JSON type only; bool is not integer and integer is not number."""
    for kind, name in ((bool, 'boolean'), (int, 'integer'), (float, 'number'), (str, 'string'),
                       (list, 'array'), (dict, 'object')):
        if isinstance(value, kind):
            return name
    if value is None:
        return 'null'
    raise CatalogError('unsupported_contract_value')


def contract_signature(args, expected):
    """Input field names with coarse types, plus the coarse result type.

    Element types and nested keys are left out on purpose: they depend on the data
    (a word-count result has different keys for every text), not on the contract.
    """
    data = args.get('data') if isinstance(args, dict) else None
    result = expected.get('result') if isinstance(expected, dict) else None
    if not isinstance(data, dict) or set(expected or {}) != {'result'}:
        raise CatalogError('unsupported_contract_shape')
    fields = ','.join(f'{key}:{coarse_type(data[key])}' for key in sorted(data))
    return f'data{{{fields}}}->{coarse_type(result)}'


def _words(text):
    return set(_WORD.findall(text.lower()))


def similarity(left, right):
    a, b = _words(left), _words(right)
    return len(a & b) / len(a | b) if a | b else 0.0


def find_reusable(catalog, *, args, expected, description, limit=100):
    """Unretired versions with the same contract signature, best description match first."""
    if not isinstance(catalog, VersionCatalog) or not isinstance(description, str):
        raise CatalogError('invalid_reuse_query')
    wanted = contract_signature(args, expected)
    matches = []
    for item in catalog.list(limit=limit)['versions']:
        if item['retired']:
            continue
        selected = catalog.inspect(item['name'], item['version'])
        doc = selected['record']['document']
        contract = doc.get('output_contract') or {}
        if contract.get('kind') != 'json-object-equals':
            continue
        try:
            if contract_signature(doc['args'], contract['expected']) != wanted:
                continue
        except CatalogError:
            continue
        matches.append({'name': item['name'], 'version': item['version'],
                        'similarity': round(similarity(description, doc['spec'].get('description', '')), 3)})
    return sorted(matches, key=lambda m: (-m['similarity'], m['name']))


def decide(catalog, *, args, expected, description):
    """Return a logged, explainable next step; never acts on it.

    A contract match is necessary but not sufficient (different tasks can share a
    contract), and word overlap with paraphrased requests is weak. So a match leads
    to `verify_reuse`: run the best-ranked version once, under normal review, on the
    requester's own example. Only a correct result makes it a reuse.
    """
    matches = find_reusable(catalog, args=args, expected=expected, description=description)
    if matches:
        best = matches[0]
        action = 'verify_reuse'
        reason = (f"contract matches {len(matches)} version(s); best description similarity "
                  f"{best['similarity']}; verify on the requester's example before reuse")
    else:
        best, action, reason = None, 'generate', 'no catalog version has this contract signature'
    return {'action': action, 'reason': reason, 'selected': best, 'candidates': matches[:5],
            'signature': contract_signature(args, expected), 'estimated_cost': COST[action],
            'fallback': 'generate' if action == 'verify_reuse' else None, 'execution_authorized': False}


def prepare_reuse_check(catalog, reviews, decision, *, args, expected):
    """Copy the selected version into a PENDING proposal bound to the requester's example."""
    if decision.get('action') != 'verify_reuse' or not decision.get('selected'):
        raise CatalogError('reuse_check_requires_verify_decision')
    if contract_signature(args, expected) != decision['signature']:
        raise CatalogError('reuse_check_contract_changed')
    selected = decision['selected']
    return catalog.prepare(selected['name'], selected['version'], reviews, args=args,
                           output_contract={'kind': 'json-object-equals', 'expected': expected})
