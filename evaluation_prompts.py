"""Opt-in prompt revisions, separate from the frozen task corpus and v1 text."""
from .evaluation_corpus import decision_prompt, generation_prompt, get_task


def evaluation_prompt(task_id, *, mode='source', version='v1'):
    if mode not in ('source', 'decision'):
        raise ValueError('invalid_evaluation_generation_mode')
    if version not in ('v1', 'v2'):
        raise ValueError('invalid_evaluation_prompt_version')
    task = get_task(task_id)
    prompt = decision_prompt(task_id) if mode == 'decision' else generation_prompt(task_id)
    if version == 'v1':
        return prompt
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
