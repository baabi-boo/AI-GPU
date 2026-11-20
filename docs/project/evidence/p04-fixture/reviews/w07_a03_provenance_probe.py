#!/usr/bin/env python3
"""Read-only provenance/layout audit against one frozen Git object tree."""

import argparse
import ast
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
revision = '10ace66193686e3862c3c218760b66c044f1d4ae'
base = '4a5df5afef1826b70a2addee5029aae9dada2da1'

def git(*parts):
    return subprocess.check_output(['git', '-C', str(args.repo), *parts])

def content(path, commit=revision):
    return git('show', commit + ':' + path)

def digest(data):
    return hashlib.sha256(data).hexdigest()

fixture_path = 'ci/project/fixtures/p04_tiny_mlp_v1.json'
manifest_path = 'ci/project/p04_model_manifest.json'
fixture_bytes = content(fixture_path)
fixture = json.loads(fixture_bytes)
manifest = json.loads(content(manifest_path))
families = ['seeded_dense', 'negated_dense', 'zero', 'signed_basis', 'split_boundary']
formats = ['fp16', 'bf16']
seeds = {'w1': 0x50403401, 'w2': 0x50403402, 'seeded_dense': 0x50403410}

# Reconstruct the documented streams independently of the producer/helper imports.
def stream(seed, count):
    state = seed
    out = []
    for _ in range(count):
        for direction, shift in [('left', 13), ('right', 17), ('left', 5)]:
            shifted = (state << shift) if direction == 'left' else (state >> shift)
            state = (state ^ shifted) & ((1 << 32) - 1)
        out.append((state % 5) - 2)
    return out

assert fixture['generator']['seeds'] == seeds
assert fixture['generator']['family_order'] == families
assert fixture['model']['formats'] == formats
weights = {'w1': (16, 8), 'w2': (8, 4)}
weight_elements = 0
for name, (rows, columns) in weights.items():
    matrix = fixture['weights']['logical'][name]
    assert len(matrix) == rows and all(len(row) == columns for row in matrix)
    assert [v for row in matrix for v in row] == stream(seeds[name], rows * columns)
    weight_elements += rows * columns
assert weight_elements == fixture['model']['weight_count'] == 160

def raw(words):
    assert all(isinstance(word, str) and re.fullmatch('[0-9a-f]{8}', word) for word in words)
    return b''.join(int(word, 16).to_bytes(4, 'little') for word in words)

def decode_packed(words, fmt):
    data = raw(words)
    if fmt == 'fp16':
        return [item[0] for item in struct.iter_unpack('<e', data)]
    return [struct.unpack('<f', (item[0] << 16).to_bytes(4, 'little'))[0]
            for item in struct.iter_unpack('<H', data)]

tensor_hashes = 0
word_count = 0
for fmt in formats:
    data = fixture['weights']['formats'][fmt]
    for name, (rows, columns) in weights.items():
        words = data[name + '_words']
        assert len(words) == rows * columns // 2
        logical = fixture['weights']['logical'][name]
        column_major = [logical[r][c] for c in range(columns) for r in range(rows)]
        assert decode_packed(words, fmt) == column_major
        assert digest(raw(words)) == data['sha256'][name]
        tensor_hashes += 1
        word_count += len(words)

dense = stream(seeds['seeded_dense'], 256)
inputs = {
    'seeded_dense': dense,
    'negated_dense': [-v for v in dense],
    'zero': [0] * 256,
    'signed_basis': [(2 if r % 2 == 0 else -2) if r == c else 0
                     for r in range(16) for c in range(16)],
    'split_boundary': [((3*r + 2*c + 3*(r//8)) % 5) - 2
                       for r in range(16) for c in range(16)],
}
expected_ids = [fmt + '-' + family for fmt in formats for family in families]
assert [case['id'] for case in fixture['cases']] == expected_ids == manifest['case_ids']
assert len(fixture['cases']) == manifest['case_count'] == 10
for case in fixture['cases']:
    assert case['id'] == case['format'] + '-' + case['family']
    assert decode_packed(case['input_words'], case['format']) == inputs[case['family']]
    for name, size in [('input', 128), ('hidden', 128), ('bridge', 64), ('output', 64)]:
        words = case[name + '_words']
        assert len(words) == size
        assert digest(raw(words)) == case['sha256'][name]
        tensor_hashes += 1
        word_count += len(words)
assert tensor_hashes == 44 and word_count == 4000
assert manifest['planned_native_launches_per_case'] == 3
assert manifest['planned_native_launches_total'] == 30
assert [step['mnk'] for step in manifest['graph'] if step['placement'] == 'native'] == [[16,8,16],[8,4,8],[8,4,8]]

assert len(manifest['artifacts']) == 17
assert len({x['path'] for x in manifest['artifacts']}) == 17
for item in manifest['artifacts']:
    assert digest(content(item['path'])) == item['sha256']
assert content('LICENSE') == content('LICENSE', base)
assert fixture['provenance']['license'] == manifest['provenance']['license'] == 'Apache-2.0'
assert fixture['provenance']['license_path'] == 'LICENSE'
assert fixture['provenance']['external_downloads'] is False
assert fixture['provenance']['pretrained_weights'] is False
assert fixture['provenance']['trained_accuracy_claimed'] is False
assert fixture['model']['tokenizer'] is None and manifest['provenance']['tokenizer'] is None
assert fixture['model']['execution_available'] is False and manifest['execution_available'] is False
assert manifest['gpu_execution_claimed'] is False
assert manifest['evidence_level'] == 'source_present'

producer_imports = []
for node in ast.walk(ast.parse(content('ci/project/p04_reference.py'))):
    if isinstance(node, ast.Import):
        producer_imports.extend(name.name for name in node.names)
    elif isinstance(node, ast.ImportFrom):
        producer_imports.append(node.module)
assert set(producer_imports) <= {'__future__', 'argparse', 'hashlib', 'json', 'pathlib', 're', 'sys', 'p02_layout_fixture_oracle'}

paths = [fixture_path, manifest_path, 'ci/project/p04_reference.py',
         'ci/project/p02_layout_fixture_oracle.py', 'LICENSE',
         'docs/designs/tiny_mlp_fixture_v1.md', 'docs/project/decisions.md']
result = {
    'scope': 'Frozen source provenance, independent weight/input reconstruction, layout and identity audit; no GPU execution or legal opinion.',
    'outcome': 'pass',
    'source_revision': revision,
    'source_tree': git('rev-parse', revision + '^{tree}').decode().strip(),
    'fixture_bytes': len(fixture_bytes),
    'fixture_sha256': digest(fixture_bytes),
    'logical_weight_count': weight_elements,
    'case_count': len(fixture['cases']),
    'case_count_per_format': 5,
    'seeds_hex': {k: hex(v) for k,v in seeds.items()},
    'verified_raw_tensor_hashes': tensor_hashes,
    'verified_raw_uint32_words': word_count,
    'encoded_tensor_bytes': word_count * 4,
    'verified_source_artifact_pins': len(manifest['artifacts']),
    'license_unchanged_from_base': True,
    'reviewed_sources': [{'path': p, 'sha256': digest(content(p))} for p in paths],
    'limitations': ['The fixture declares repository-original synthetic data; this review establishes its direct deterministic derivation, not independent legal title.',
                    'No trained quality, model executor, accelerated dispatch, native arithmetic, transfer timing, FPGA or silicon result is established.',
                    'The existing numerical and host helper suites were not rerun; hidden/bridge/output arrays were checked for canonical shape and raw hash identity here.']
}
args.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k,v in result.items() if k not in {'reviewed_sources','limitations'}}, indent=2))
