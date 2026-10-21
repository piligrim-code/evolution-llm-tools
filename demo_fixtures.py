"""Hand-written synthetic examples. Preparing a fixture never executes its code."""
from copy import deepcopy

_FIXTURES = {
    'text-summary': {
        'spec': {'name': 'demo_text_summary', 'description': 'Count words and distinct tokens in synthetic text.',
                 'args': [{'name': 'text', 'type': 'string'}], 'output': 'JSON word and unique-token counts'},
        'scripts': {'tool.py': '''import json, sys
args = json.loads(sys.argv[2])
if type(args.get('text')) is not str:
    raise ValueError('text must be a string')
words = args['text'].split()
print(json.dumps({'words': len(words), 'unique_words': len(set(words))}))
'''},
        'args': {'text': '  alpha beta\nalpha  '},
        'output_contract': {'kind': 'json-object-equals', 'expected': {'words': 3, 'unique_words': 2}},
    },
    'table-totals': {
        'spec': {'name': 'demo_table_totals', 'description': 'Sum synthetic integer amounts by group.',
                 'args': [{'name': 'rows', 'type': 'array'}], 'output': 'JSON group totals, row count and grand total'},
        'scripts': {'tool.py': '''import json, sys
from collections import defaultdict
args = json.loads(sys.argv[2])
rows = args['rows']
if type(rows) is not list:
    raise ValueError('rows must be a list')
totals = defaultdict(int)
for row in rows:
    if (type(row) is not dict or type(row.get('group')) is not str
            or not row['group'] or type(row.get('amount')) is not int):
        raise ValueError('each row requires a group and an integer amount')
    totals[row['group']] += row['amount']
print(json.dumps({'totals': dict(totals), 'rows': len(rows), 'total': sum(totals.values())}))
'''},
        'args': {'rows': [{'group': 'A', 'amount': 3}, {'group': 'B', 'amount': 5}, {'group': 'A', 'amount': 4}]},
        'output_contract': {'kind': 'json-object-equals', 'expected': {'totals': {'A': 7, 'B': 5}, 'rows': 3, 'total': 12}},
    },
    'json-projection': {
        'spec': {'name': 'demo_json_projection', 'description': 'Validate and project fields from synthetic JSON.',
                 'args': [{'name': 'data', 'type': 'object'}], 'output': 'JSON name, active flag and summed scores'},
        'scripts': {'tool.py': '''import json, sys
data = json.loads(sys.argv[2])['data']
if (type(data) is not dict or type(data.get('name')) is not str
        or type(data.get('active')) is not bool or type(data.get('scores')) is not list
        or any(type(score) is not int for score in data['scores'])):
    raise ValueError('name, active and integer scores are required')
print(json.dumps({'name': data['name'], 'active': data['active'], 'score_total': sum(data['scores'])}))
'''},
        'args': {'data': {'name': 'Ada', 'active': True, 'scores': [2, 4], 'internal_note': 'synthetic-only'}},
        'output_contract': {'kind': 'json-object-equals', 'expected': {'name': 'Ada', 'active': True, 'score_total': 6}},
    },
}


def list_demos():
    return [{'name': name, 'description': fixture['spec']['description']} for name, fixture in _FIXTURES.items()]


def get_demo(name):
    if not isinstance(name, str) or name not in _FIXTURES:
        raise ValueError('unknown_demo')
    return deepcopy(_FIXTURES[name])


def prepare_demo(name, policy, reviews):
    fixture = get_demo(name)
    identifier = reviews.create(fixture['spec'], fixture['scripts'], fixture['args'], policy,
                                output_contract=fixture['output_contract'])
    return {'id': identifier, 'demo': name, 'state': 'pending', 'execution_authorized': False}
