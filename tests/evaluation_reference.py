"""Handwritten synthetic baselines, executed only in explicitly opted-in containers."""
BODIES = {
    'integer-sum': "result = sum(data['values'])",
    'stable-unique': "result = list(dict.fromkeys(data['values']))",
    'word-counts': "from collections import Counter\nresult = dict(Counter(data['text'].lower().split()))",
    'group-totals': "result = {}\nfor row in data['rows']:\n    result[row['group']] = result.get(row['group'], 0) + row['amount']",
    'active-ids': "result = [row['id'] for row in data['rows'] if row['active'] is True]",
    'median': "import statistics\nresult = float(statistics.median(data['values'])) if data['values'] else None",
    'clamp-values': "result = [max(data['low'], min(data['high'], value)) for value in data['values']]",
    'chunk-list': "result = [data['values'][i:i+data['size']] for i in range(0, len(data['values']), data['size'])]",
    'flatten-once': "result = [value for group in data['arrays'] for value in group]",
    'dot-product': "result = sum(a*b for a, b in zip(data['a'], data['b']))",
    'sort-records': "result = [row['name'] for row in sorted(data['rows'], key=lambda row: (-row['score'], row['name']))]",
    'date-distance': "from datetime import date\nresult = (date.fromisoformat(data['end']) - date.fromisoformat(data['start'])).days",
    'csv-projection': "import csv, io\nresult = [row[data['field']] for row in csv.DictReader(io.StringIO(data['text']))]",
    'json-project': "result = {key: data['object'][key] for key in data['keys'] if key in data['object']}",
    'run-length': "from itertools import groupby\nresult = [[key, sum(1 for _ in group)] for key, group in groupby(data['values'])]",
    'balanced-parentheses': "balance = 0\nresult = True\nfor char in data['text']:\n    balance += (char == '(') - (char == ')')\n    if balance < 0:\n        result = False\nresult = result and balance == 0",
}


def scripts_for(task_id):
    return {'tool.py': "import json, sys\ndata = json.loads(sys.argv[2])['data']\n" +
            BODIES[task_id] + "\nprint(json.dumps({'result': result}))\n"}
