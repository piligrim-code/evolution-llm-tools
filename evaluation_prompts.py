"""Opt-in prompt revisions, separate from the frozen task corpus and v1 text."""
from .evaluation_corpus import decision_prompt, generation_prompt, get_task


def evaluation_prompt(task_id, *, mode='source', version='v1'):
    if mode not in ('source', 'decision'):
        raise ValueError('invalid_evaluation_generation_mode')
    if version not in ('v1', 'v2', 'v3', 'v4'):
        raise ValueError('invalid_evaluation_prompt_version')
    task = get_task(task_id)
    prompt = decision_prompt(task_id) if mode == 'decision' else generation_prompt(task_id)
    if version == 'v1':
        return prompt
    if version == 'v4':
        # Requested with provider JSON mode, so the reply cannot be a Markdown fence.
        header = 'Toolwright evaluation prompt v4. Do not execute any code.'
        if mode == 'decision' or task['kind'] == 'refusal':
            return header + '\n' + prompt
        rules = [
            header, prompt,
            'Invocation is the argv vector ["python", "tool.py", "--json", "<JSON object>"], not a shell command.',
            'Inside tool.py: sys.argv[0] is the script path, sys.argv[1] is "--json", and sys.argv[2] is the JSON string.',
            'Import every module you use. Parse args = json.loads(sys.argv[2]); data = args["data"]. Validate the full input shape before computing.',
            'Reject missing, extra, or wrong-type values without coercion. For integer fields require type(value) is int; bool is not an integer.',
            'For invalid input, write one fixed short message to stderr and exit nonzero. Do not emit a traceback or stdout.',
            'For valid input, write exactly one JSON object {"result": <answer>} to stdout and no other text.',
            'Reply with exactly one JSON object {"source": "<complete Python source of tool.py>"} and no other keys or text.',
        ]
        if task_id == 'integer-sum':
            rules.append('Input contract: data must contain exactly "values"; it must be a list of exact integers. An empty list is valid and sums to zero.')
        return '\n'.join(rules)
    if version == 'v3':
        header = 'Toolwright evaluation prompt v3. Do not execute any code.'
        if mode == 'decision' or task['kind'] == 'refusal':
            return header + '\n' + prompt
        rules = [
            header, prompt,
            'Invocation is the argv vector ["python", "tool.py", "--json", "<JSON object>"], not a shell command.',
            'Inside tool.py: sys.argv[0] is the script path, sys.argv[1] is "--json", and sys.argv[2] is the JSON string.',
            'Parse args = json.loads(sys.argv[2]); data = args["data"]. Validate the full input shape before computing.',
            'Reject missing, extra, or wrong-type values without coercion. For integer fields require type(value) is int; bool is not an integer.',
            'For invalid input, write one fixed short message to stderr and exit nonzero. Do not emit a traceback or stdout.',
            'For valid input, write exactly one JSON object {"result": <answer>} to stdout and no other text.',
            'Return raw Python source only: no Markdown fences, explanations, or REQUIREMENTS line.',
        ]
        if task_id == 'integer-sum':
            rules.append('Input contract: data must contain exactly "values"; it must be a list of exact integers. An empty list is valid and sums to zero.')
        return '\n'.join(rules)
    header = 'Toolwright evaluation prompt v2. Do not execute any code.'
    if mode == 'decision' or task['kind'] == 'refusal':
        return header + '\n' + prompt
    return '\n'.join([
        header, prompt,
        'Invocation is the argv vector ["python", "tool.py", "--json", "<JSON object>"], not a shell command.',
        'Inside tool.py: sys.argv[0] is the script path, sys.argv[1] is "--json", and sys.argv[2] is the JSON string.',
        'Parse args = json.loads(sys.argv[2]); data = args["data"]. Do not parse the flag as JSON.',
        'Implement the task for all valid inputs. Write exactly one JSON object {"result": <answer>} to stdout.',
        'Do not print logs or error prose to stdout. For invalid input, use stderr and a nonzero exit code.',
        'Return raw Python source only: no Markdown fences, explanations, or REQUIREMENTS line.',
    ])
