from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path('/workspace/scratch/98908dfa3444/AI-GPU')
SCRATCH = ROOT.parent
DISCOVERY = SCRATCH / 'w09-hosted-checkpoint-review-discovery.json'
STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ?')
ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
START = re.compile(r'^(test_\S+) \((test_[A-Za-z0-9_.]+)\)(.*)$')
TERMINAL = re.compile(r'\.\.\. (ok|FAIL|ERROR|expected failure|unexpected success|skipped(?: .*)?)$')

def parse(path):
    body = path.read_bytes()
    text = body.decode('utf-8')
    lines = [ANSI.sub('', STAMP.sub('', line)) for line in text.splitlines()]
    summaries = [(i + 1, re.fullmatch(r'Ran (\d+) tests? in ([0-9.]+)s', line))
                 for i, line in enumerate(lines)]
    summaries = [(number, match) for number, match in summaries if match]
    assert len(summaries) == 1, summaries
    summary_line, summary = summaries[0]
    entries = []
    pending = None
    for number, line in enumerate(lines[:summary_line - 1], 1):
        start = START.match(line)
        if start:
            assert pending is None, (pending, number, line)
            method, identifier, rest = start.groups()
            assert identifier.endswith('.' + method), (number, line)
            pending = {'id': identifier, 'method': method, 'start_line': number}
        terminal = TERMINAL.search(line)
        if terminal and pending:
            pending.update(result=terminal.group(1), result_line=number)
            entries.append(pending)
            pending = None
    assert pending is None, pending
    ids = [row['id'] for row in entries]
    assert len(ids) == len(set(ids)), 'duplicate test IDs'
    assert int(summary.group(1)) == len(ids), (summary.group(1), len(ids))
    results = Counter(row['result'] for row in entries)
    overall = next((line for line in lines[summary_line:] if line), None)
    sources = [(i + 1, line) for i, line in enumerate(lines) if line.startswith('Source: ')]
    interpreters = [(i + 1, line) for i, line in enumerate(lines)
                    if re.fullmatch(r'3\.12\.\d+ \(.*\) \[GCC .*\]', line)]
    commands = [(i + 1, line.removeprefix('##[group]Run '))
                for i, line in enumerate(lines) if line.startswith('##[group]Run python3 ')]
    result = {
        'path': str(path), 'sha256': hashlib.sha256(body).hexdigest(), 'size_bytes': len(body),
        'line_count': len(lines), 'source_lines': sources, 'interpreter_lines': interpreters,
        'command_lines': commands, 'summary_line': summary_line,
        'tests': int(summary.group(1)), 'seconds': float(summary.group(2)),
        'overall_result': overall, 'unique_test_ids': len(set(ids)), 'results': dict(results),
        'multiline_test_result_ids': [row['id'] for row in entries if row['start_line'] != row['result_line']],
        'ids_sha256_sorted_lf_utf8': hashlib.sha256(('\n'.join(sorted(ids)) + '\n').encode()).hexdigest(),
        'modules': dict(sorted(Counter(row['id'].split('.')[0] for row in entries).items())),
        'test_results': entries,
    }
    return result

def main():
    discovery = json.loads(DISCOVERY.read_bytes())
    parent = parse(ROOT / 'docs/project/evidence/p06-counter-diagnostics/host/run-45031746158-job-137236633104.log')
    assert parent['tests'] == 3158 and parent['overall_result'] == 'OK' and parent['results'] == {'ok': 3158}
    parent_ids = {row['id'] for row in parent['test_results']}
    expected_ids = set(discovery['all_discovered_test_ids'])
    new_ids = {identifier for module in discovery['modules'].values() for identifier in module['test_ids']}
    assert not parent_ids - expected_ids
    assert expected_ids - parent_ids == new_ids
    result = {
        'reviewed_at_utc': datetime.now(timezone.utc).isoformat(),
        'parser_scope': 'Read retained decoded logs as UTF-8 data; no test or producer code executed',
        'parent': parent,
        'parent_ids_subset_of_current_discovery': True,
        'current_discovery_minus_parent_is_exact_four_module_delta': True,
        'new_unique_test_ids': sorted(new_ids),
    }
    suffix = 'parent-log'
    if len(sys.argv) == 2:
        current = parse(Path(sys.argv[1]))
        actual_ids = {row['id'] for row in current['test_results']}
        result.update(current=current,
                      hosted_ids_match_current_discovery=actual_ids == expected_ids,
                      hosted_missing_ids=sorted(expected_ids - actual_ids),
                      hosted_extra_ids=sorted(actual_ids - expected_ids))
        result['new_module_results'] = {
            name: {'tests': sum(row['id'].startswith(name + '.') for row in current['test_results']),
                   'outcomes': dict(Counter(row['result'] for row in current['test_results']
                                            if row['id'].startswith(name + '.')))}
            for name in discovery['modules']}
        suffix = 'completed-log'
    destination = SCRATCH / ('w09-hosted-checkpoint-review-' + suffix + '.json')
    destination.write_text(json.dumps(result, indent=2) + '\n')
    selected = result.get('current', parent)
    print(json.dumps({'output': str(destination), 'tests': selected['tests'], 'seconds': selected['seconds'],
                      'overall': selected['overall_result'], 'unique_ids': selected['unique_test_ids'],
                      'results': selected['results'], 'source_lines': selected['source_lines'],
                      'multiline_result_count': len(selected['multiline_test_result_ids']),
                      'delta_identity_verified': True,
                      'hosted_ids_match_current_discovery': result.get('hosted_ids_match_current_discovery')}))

if __name__ == '__main__':
    main()
