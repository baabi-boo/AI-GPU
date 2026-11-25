#!/usr/bin/env python3
"""Bounded independent retention probes; no native execution or repository edit."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

REPO = Path('/tmp/ai-gpu-ae456f837c05/AI-GPU')
NOTES = REPO.parent / 'notes'
sys.path.insert(0, str(REPO / 'ci/project'))
import p06_qualified_warm_retention as retention
from test_p06_qualified_warm_retention import fixture, REVISION

observed = []
with tempfile.TemporaryDirectory(prefix='agent17-') as temporary:
    root = Path(temporary)
    archive = root / 'archive.tar'
    summary_path = root / 'summary.json'

    def inspect(body, revision=REVISION, summary=None):
        archive.write_bytes(body)
        return retention.inspect_archive(archive, hashlib.sha256(body).hexdigest(),
                                         expected_revision=revision, summary=summary)

    def rejected(label, body, expected, summary=None):
        try:
            inspect(body, summary=summary)
        except retention.RetentionError as error:
            assert error.code == expected, (label, error.code, expected)
            observed.append({'case': label, 'result': 'rejected', 'code': error.code})
        else:
            raise AssertionError(label + ' accepted')

    baseline, manifest, raw = fixture()
    for label, token, expected in (
        ('integer-above-file-limit', str(1 << 256).encode(), 'file-limit'),
        ('negative-size', b'-1', 'file-limit'),
        ('negative-zero-size', b'-0', 'manifest-format'),
        ('integer-over-runtime-digit-limit', b'9' * 4301, 'manifest-format'),
        ('float-exponent', b'1e1', 'manifest-format'),
    ):
        body = raw.replace(b'"size_bytes":15', b'"size_bytes":' + token)
        rejected(label, fixture(manifest_bytes=body)[0], expected)

    nested_duplicate = raw.replace(b'"size_bytes":15', b'"size_bytes":15,"size_bytes":15')
    rejected('nested-duplicate-size', fixture(manifest_bytes=nested_duplicate)[0], 'manifest-format')
    for label, names in (
        ('unicode-casefold-expansion', ('ss', '\u00df')),
        ('unicode-final-sigma', ('\u03c2', '\u03c3')),
    ):
        rejected(label, fixture({name: b'x' for name in names})[0], 'path-alias')
    invalid_directories = copy.deepcopy(manifest)
    invalid_directories['directories'] = ['', False]
    rejected('directory-boolean', fixture(manifest=invalid_directories)[0], 'manifest-schema')

    pax, _, _ = fixture({'\u00e9': b'x'})
    pax_record = b'19 path=private/\xc3\xa9\n'
    assert pax.count(pax_record) == 1
    rejected('pax-record-length', pax.replace(pax_record, b'18' + pax_record[2:]), 'archive-format')
    rejected('pax-record-terminator', pax.replace(pax_record, pax_record[:-1] + b'\x00'), 'archive-format')
    fallback_end = pax.index(b'private/?') + len(b'private/?')
    changed = bytearray(pax)
    changed[fallback_end + 1] = ord('x')
    rejected('pax-fallback-after-nul', bytes(changed), 'archive-format')

    summary = {'schema_version': 1, 'contract_id': retention.RETENTION_CONTRACT_ID,
               'expected_revision': REVISION, 'outcome': 'pass', 'encryption_passed': True,
               'file_count': 1, 'directory_count': 1, 'input_bytes': 15,
               'ciphertext_bytes': 1, 'ciphertext_sha256': 'f' * 64}
    for label, key, value, expected in (
        ('summary-negative-count', 'directory_count', -1, 'summary-mismatch'),
        ('summary-count-float', 'input_bytes', 15.0, 'summary-format'),
        ('summary-ciphertext-zero', 'ciphertext_bytes', 0, 'summary-format'),
        ('summary-ciphertext-huge', 'ciphertext_bytes', 1 << 100, 'summary-format'),
        ('summary-extra-private-key', 'private_path', '/opaque', 'summary-format'),
    ):
        summary_path.write_text(json.dumps(dict(summary, **{key: value})), encoding='utf-8')
        rejected(label, baseline, expected, summary_path)
    summary_body = json.dumps(summary).encode()
    summary_path.write_bytes(summary_body.replace(b'"file_count": 1', b'"file_count": 1,"file_count": 1'))
    rejected('summary-duplicate-key', baseline, 'summary-format', summary_path)
    summary_path.write_bytes(b' ' * (retention.MAX_SUMMARY_BYTES + 1))
    rejected('summary-real-byte-limit', baseline, 'summary-byte-limit', summary_path)

    summary_path.write_text(json.dumps(summary), encoding='utf-8')
    report = inspect(baseline, summary=summary_path)
    assert report['summary_checked'] is True
    assert 'public-summary-ciphertext-is-not-verified' in report['limitations']
    assert report['origin_authenticated'] is False
    observed.append({'case': 'summary-syntax-only-ciphertext', 'result': 'accepted-as-consistency-only'})

    real_root = REPO.parent / 'roundtrip-agent14'
    real_tar = real_root / 'reviewer-private/decrypted-retention.PRIVATE.tar'
    real_summary = real_root / 'public-delivery/encryption-summary.json'
    real_digest = hashlib.sha256(real_tar.read_bytes()).hexdigest()
    assert real_digest == '9e62d2a1637f2e1fe77c47daa2e16128000876645ab4e91d7fd00c82b9092613'
    with mock.patch('subprocess.Popen', side_effect=AssertionError('must remain inert')), \
         mock.patch('tarfile.TarFile.extract', side_effect=AssertionError('must remain inert')), \
         mock.patch('tarfile.TarFile.extractall', side_effect=AssertionError('must remain inert')):
        real_report = retention.inspect_archive(real_tar, real_digest,
            expected_revision='622662ad9cece6da4e3375be7e977dbe04cde862', summary=real_summary)
    assert real_report['file_count'] == 8
    assert real_report['directory_count'] == 3
    assert real_report['input_bytes'] == 8680
    assert real_report['native_execution'] == 'not_run'
    for key in ('retained_code_executed', 'origin_authenticated', 'native_acceptance',
                'performance_acceptance', 'phase_acceptance'):
        assert real_report[key] is False
    observed.append({'case': 'actual-decrypted-synthetic-archive', 'result': 'accepted',
                     'plaintext_sha256': real_digest, 'archive_bytes': real_report['archive_bytes'],
                     'file_count': 8, 'directory_count': 3, 'input_bytes': 8680,
                     'native_execution': 'not_run'})

source_paths = ['ci/project/p06_qualified_warm_retention.py',
                'ci/project/p06_qualified_warm_encrypt.py',
                'ci/project/p06_qualified_warm_restore.py',
                'ci/project/test_p06_qualified_warm_retention.py',
                'ci/project/test_p06_qualified_warm_retention_integration.py',
                'docs/designs/qualified_warm_retention_review_v1.md']
result = {'outcome': 'pass', 'python': sys.version.split()[0],
          'integer_digit_limit': sys.get_int_max_str_digits(),
          'observations': observed, 'production_modified': False, 'native_execution': 'not_run',
          'source_hashes': {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
                            for name in source_paths}}
(NOTES / 'agent-17-probes.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'outcome': 'pass', 'observations': len(observed),
                  'rejected': sum(row['result'] == 'rejected' for row in observed),
                  'native_execution': 'not_run'}))
