"""Normalize provider-decoded unittest result rows without executing log content."""
from pathlib import Path
import hashlib
import json
import re

source = Path('../validation/d8-hosted-governance-decoded.log')
raw = source.read_bytes()
lines = [re.sub(r'^\d{4}-\d\d-\d\dT\S+Z\s?', '', line)
         for line in raw.decode().splitlines()]
start = re.compile(r'^(test_\S+|setUpClass) \(([^)]+)\)(?: \.\.\.\s*(.*))?$')
outcome = re.compile(r'^(ok|FAIL|ERROR|skipped\b.*|expected failure|unexpected success)$')
rows = []
pending = None
first = last = None
for index, line in enumerate(lines):
    match = start.match(line)
    if match:
        assert pending is None, pending
        pending = {'label': match[1], 'id': match[2], 'log_line': index + 1,
                   'kind': 'class_setup' if match[1] == 'setUpClass' else 'method'}
        first = index if first is None else first
        tail = match[3] or ''
        if outcome.fullmatch(tail):
            pending['result'] = tail
            rows.append(pending)
            pending = None
    elif pending:
        tail = line.rsplit(' ... ', 1)[-1].strip()
        if outcome.fullmatch(tail):
            pending['result'] = tail
            rows.append(pending)
            pending = None
    if re.fullmatch(r'OK(?: \(skipped=\d+\))?', line):
        last = index
assert pending is None, pending
summary = [line for line in lines if re.match(r'^(Ran \d+ tests|OK\b|FAILED\b)', line)]
result = {
    'schema_version': 1,
    'run_id': 45352860975,
    'job_id': 138303493193,
    'run_attempt': 1,
    'source_revision': 'd8abc24d2fd5dab5ceddbae3627e3d3eb9750358',
    'provider_conclusion': 'success',
    'run_url': 'https://github.com/baabi-boo/AI-GPU/actions/runs/45352860975',
    'retrieval': 'GitHub fetch_workflow_job_logs decoded text; timestamp prefixes removed for result rows',
    'decoded_log_sha256': hashlib.sha256(raw).hexdigest(),
    'decoded_log_size_bytes': len(raw),
    'summary_lines': summary,
    'source_identity_lines': [line for line in lines if line.startswith('Source: ')],
    'method_results': sum(row['kind'] == 'method' for row in rows),
    'passed_methods': sum(row['kind'] == 'method' and row['result'] == 'ok' for row in rows),
    'method_skip_events': sum(row['kind'] == 'method' and row['result'].startswith('skipped') for row in rows),
    'class_skip_events': sum(row['kind'] == 'class_setup' and row['result'].startswith('skipped') for row in rows),
    'rows': rows,
    'full_zero_skip_coverage': False,
    'native_execution': 'not_run',
}
assert len({(row['kind'], row['id']) for row in rows}) == len(rows)
assert result['method_results'] == 4610
assert result['passed_methods'] == 4589
assert result['method_skip_events'] == 21 and result['class_skip_events'] == 2
assert summary == ['Ran 4610 tests in 2311.819s', 'OK (skipped=23)']
assert first is not None and last is not None
Path('../validation/d8-hosted-governance-results.json').write_text(json.dumps(result, indent=2) + '\n')
Path('../validation/d8-hosted-governance-test-step.log').write_text('\n'.join(lines[first:last + 1]) + '\n')
print(json.dumps({key: value for key, value in result.items() if key != 'rows'}))
