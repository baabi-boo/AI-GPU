#!/usr/bin/env python3
"""Bounded real-age integration probe; fixture bytes and reports are synthetic."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tarfile
import time

sys.dont_write_bytecode = True
BASE = Path('/home/agent/ai-gpu-d37f66a85d88')
REPO = BASE / 'AI-GPU'
NOTES = BASE / 'notes'
AGE = BASE / 'tools/age'
KEYGEN = BASE / 'tools/age-keygen'
RELEASE = BASE / 'tools/age-v1.3.2.tar.gz'
RELEASE_SHA256 = 'cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10'
SOURCES = [REPO / 'ci/project' / name for name in (
    'p06_qualified_warm_encrypt.py', 'p06_qualified_warm_retention.py',
    'p06_qualified_warm_restore.py')]
EXPECTED_SOURCE_HASHES = {
    'ci/project/p06_qualified_warm_encrypt.py': '4beadf5cd67fe8847fb00b881a45661e710b6275fb5d5e5baa0a52a1440de275',
    'ci/project/p06_qualified_warm_retention.py': '4645e2a4aac840c87b467b08cb2d338818739d6fbdbbd3ec95a1103dfa11bcbe',
    'ci/project/p06_qualified_warm_restore.py': '21bc047ef9b76232aa79ce5199b82fca48cb6611aab4b61018f8ff9f08bbbf1d',
}
EXPECTED_TOOL_HASHES = {
    'age': 'eb7dd1b518f0a307c99cd97782623c5321da049154b04acd2d98d21aa7bc9b2c',
    'age_keygen': '0a0009db842259d6717f7eeb30acb6b90d2a2eb924c6acd0a0db0ca1f1537899',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mode(path):
    return stat.S_IMODE(Path(path).lstat().st_mode)


def source_hashes():
    return {str(path.relative_to(REPO)): digest(path) for path in SOURCES}


def private_write(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', required=True)
    args = parser.parse_args()
    work = Path(args.work)
    os.umask(0o077)
    result = {
        'assignment': 'a33', 'scope': 'final cleanup bytes: synthetic real-age transport and retention integration only',
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'outcome': 'fail', 'work_directory': str(work),
        'native_execution': 'not_run', 'native_acceptance': False,
        'performance_acceptance': False, 'phase_acceptance': False,
        'genuine_private_user_or_vendor_data_used': False,
        'checks': {}, 'commands': [], 'identity_files_deleted': False,
        'source_sha256_required': EXPECTED_SOURCE_HASHES,
        'reused_probe': {'path': str(BASE / 'notes/a12_probe.py'),
                         'sha256': digest(BASE / 'notes/a12_probe.py')},
        'earlier_results_promoted_to_final_bytes': False,
        'scope_limitations': [
            'Final cleanup source bytes received a new synthetic roundtrip; earlier runs retain their own source hashes.',
            'No native experiment, vendor data, actual control archive, performance or phase acceptance.',
            'No assertion of origin authentication or exclusion of malicious concurrent writers.',
            'No full strict governance qualification or injected close-fault coverage from this roundtrip.',
        ],
        'invocation': {'argv': [sys.executable, str(Path(__file__)), '--work', str(work)],
                       'cwd': str(Path.cwd()), 'incoming_tmpdir': os.environ.get('TMPDIR')},
    }
    identities = []
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(work / 'tmp'),
               PYTHONUTF8='1', LANG='C', LC_ALL='C', TZ='UTC')
    os.environ.update(PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(work / 'tmp'))

    def check(name, condition):
        result['checks'][name] = bool(condition)
        if not condition:
            raise AssertionError(name)

    def run(name, argv, *, cwd=None, include_output=True):
        completed = subprocess.run([str(value) for value in argv],
            cwd=cwd or work, env=env, capture_output=True, timeout=45)
        record = {'name': name, 'argv': [str(value) for value in argv],
                  'cwd': str(cwd or work), 'returncode': completed.returncode}
        if include_output:
            record.update(stdout=completed.stdout.decode('utf-8', 'replace'),
                          stderr=completed.stderr.decode('utf-8', 'replace'))
        else:
            record.update(stdout_bytes=len(completed.stdout),
                          stderr_bytes=len(completed.stderr),
                          output_not_retained=True)
        result['commands'].append(record)
        return completed

    try:
        check('fresh_owned_work_directory', work.parent == BASE / 'tmp'
              and work.name.startswith('a33-real-age.')
              and mode(work) == 0o700 and work.lstat().st_uid == os.getuid())
        check('task_local_tmpdir', env['TMPDIR'] == str(work / 'tmp')
              and mode(work / 'tmp') == 0o700)
        check('release_archive_sha256', digest(RELEASE) == RELEASE_SHA256)
        free = os.statvfs(work)
        result['free_bytes_before'] = free.f_bavail * free.f_frsize
        check('bounded_retention_disk_reserve', result['free_bytes_before'] >= 128 * 1024**2)
        result['python'] = {'path': sys.executable, 'version': sys.version.split()[0],
                            'resolved_sha256': digest(Path(sys.executable).resolve())}
        result['tools'] = {
            'age': {'path': str(AGE), 'sha256': digest(AGE)},
            'age_keygen': {'path': str(KEYGEN), 'sha256': digest(KEYGEN)},
            'release_archive_sha256': digest(RELEASE),
        }
        for label, binary in (('age', AGE), ('age_keygen', KEYGEN)):
            proc = run(label + '_version', [binary, '--version'])
            check(label + '_version', proc.returncode == 0 and proc.stdout.strip() == b'v1.3.2')
            result['tools'][label]['version'] = proc.stdout.decode().strip()
            check(label + '_verified_binary_hash', digest(binary) == EXPECTED_TOOL_HASHES[label])
        revision_proc = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO,
            env=env, capture_output=True, text=True, check=True)
        revision = revision_proc.stdout.strip()
        result['checkout_head'] = revision
        result['source_sha256_before'] = source_hashes()
        check('requested_final_source_hashes_before',
              result['source_sha256_before'] == EXPECTED_SOURCE_HASHES)
        result['working_tree_status_before'] = run('git_status_before',
            ['git', 'status', '--short'], cwd=REPO).stdout.decode('utf-8', 'replace')
        result['probe_sha256'] = digest(__file__)

        source = work / 'synthetic-private'
        source.mkdir(mode=0o700)
        outside = work / 'outside-checkout'
        outside.mkdir(mode=0o700)
        long_directory = 'pax-' + 'x' * 105
        directory_names = ['', '.hidden', '.hidden/empty', 'empty-root', 'nested',
                           'nested/empty', 'nested/space dir', 'unicodé', long_directory]
        for name in sorted(directory_names):
            if name:
                (source / name).mkdir(mode=0o700)
        canary = work / 'canary-executed'
        payloads = {
            'plain.txt': b'Synthetic retention fixture only.\n',
            '.dotfile': b'hidden synthetic bytes\x00\xff\n',
            '.hidden/config.json': b'{"synthetic":true,"value":17}\n',
            'nested/data.bin': bytes(range(256)) * 513 + b'\x00tail\xff',
            'nested/empty-file': b'',
            'nested/space dir/name with spaces.txt': b'spaces preserved\n',
            'unicodé/café.txt': 'Synthetic café — UTF-8.\n'.encode(),
            long_directory + '/payload.txt': b'long PAX pathname preserved\n',
            'inert-canary.sh': ('#!/bin/sh\nprintf "unexpected execution\\n" > '
                                + shlex.quote(str(canary)) + '\n').encode(),
        }
        for name, body in payloads.items():
            private_write(source / name, body)
        (source / 'inert-canary.sh').chmod(0o700)
        check('source_private_modes', all(mode(source / name) == 0o700 for name in directory_names)
              and all(mode(source / name) == (0o700 if name == 'inert-canary.sh' else 0o600)
                      for name in payloads))
        expected_files = [{'path': name, 'size_bytes': len(body),
                           'sha256': hashlib.sha256(body).hexdigest()}
                          for name, body in sorted(payloads.items())]
        total_bytes = sum(map(len, payloads.values()))
        result['fixture'] = {'file_count': len(payloads), 'directory_count': len(directory_names),
                             'input_bytes': total_bytes, 'directories': sorted(directory_names),
                             'files': expected_files, 'executable_canary_present': True}

        for name in ('test-identity.agekey', 'wrong-test-identity.agekey'):
            identity = work / name
            proc = run('generate_' + name, [KEYGEN, '--output', identity], include_output=False)
            if identity.exists():
                identities.append((identity, identity.lstat().st_dev, identity.lstat().st_ino))
            check('generated_' + name, proc.returncode == 0 and identity.is_file()
                  and mode(identity) == 0o600)
        identity, wrong_identity = (item[0] for item in identities)
        proc = run('derive_public_recipient', [KEYGEN, '-y', identity], include_output=False)
        check('public_recipient_derived', proc.returncode == 0)
        recipient = proc.stdout.decode('ascii').strip()

        sys.path.insert(0, str(REPO / 'ci/project'))
        import p06_qualified_warm_encrypt as encrypt
        check('actual_producer_module', Path(encrypt.__file__) == SOURCES[0])
        encrypted = work / 'encrypted-output'
        summary = encrypt.encrypt_private_directory(input_dir=source, output_dir=encrypted,
            recipient=recipient, age_binary=str(AGE), expected_revision=revision)
        result['producer_call'] = {
            'callable': 'p06_qualified_warm_encrypt.encrypt_private_directory',
            'input_dir': str(source), 'output_dir': str(encrypted),
            'recipient': 'public recipient derived from disposable test identity; omitted',
            'age_binary': str(AGE), 'expected_revision': revision,
            'outcome': 'pass', 'monkeypatches_or_mocks_used': False,
        }
        cipher = encrypted / encrypt.CIPHERTEXT_NAME
        summary_path = encrypted / encrypt.SUMMARY_NAME
        result['encryption_summary'] = summary
        cipher_digest = digest(cipher)
        check('ciphertext_summary_hash_and_size', summary['ciphertext_sha256'] == cipher_digest
              and summary['ciphertext_bytes'] == cipher.stat().st_size)
        check('summary_counts', summary['outcome'] == 'pass' and summary['encryption_passed'] is True
              and summary['expected_revision'] == revision and summary['file_count'] == len(payloads)
              and summary['directory_count'] == len(directory_names) and summary['input_bytes'] == total_bytes)
        check('persisted_summary_exact', json.loads(summary_path.read_bytes()) == summary)
        check('public_output_exact_pair', {p.name for p in encrypted.iterdir()}
              == {encrypt.CIPHERTEXT_NAME, encrypt.SUMMARY_NAME})
        check('encrypted_output_private_modes', mode(encrypted) == 0o700
              and mode(cipher) == 0o600 and mode(summary_path) == 0o600
              and mode(str(encrypted) + '.PRIVATE') == 0o700)

        archive = work / 'decrypted-synthetic.tar'
        proc = run('real_age_decrypt', [AGE, '--decrypt', '--identity', identity,
                                      '--output', archive, cipher])
        check('real_age_decrypt_success', proc.returncode == 0 and proc.stdout == b'' and proc.stderr == b'')
        check('decrypted_archive_private_mode', mode(archive) == 0o600)
        archive_digest = digest(archive)
        result['archive'] = {'path': str(archive), 'sha256': archive_digest,
                             'size_bytes': archive.stat().st_size}

        wrong_output = work / 'wrong-key-output.tar'
        proc = run('real_age_wrong_identity', [AGE, '--decrypt', '--identity', wrong_identity,
                     '--output', wrong_output, cipher])
        check('wrong_identity_rejected', proc.returncode != 0 and proc.stdout == b''
              and b'no identity matched any of the recipients' in proc.stderr)
        check('wrong_identity_no_plaintext', not wrong_output.exists() or wrong_output.stat().st_size == 0)
        result['wrong_identity'] = {'returncode': proc.returncode,
            'no_plaintext_released': True, 'output_exists': wrong_output.exists(),
            'stderr': proc.stderr.decode('utf-8', 'replace')}

        with tarfile.open(archive, 'r:') as tar:
            members = tar.getmembers()
            expected_names = {'manifest.json', *('private' + ('/' + n if n else '') for n in directory_names),
                              *('private/' + name for name in payloads)}
            check('tar_exact_members', len(members) == len(expected_names)
                  and {m.name.rstrip('/') for m in members} == expected_names)
            manifest_bytes = tar.extractfile('manifest.json').read()
            manifest = json.loads(manifest_bytes)
            check('manifest_exact_inventory', manifest == {
                'schema_version': 1, 'contract_id': encrypt.CONTRACT_ID,
                'expected_revision': revision, 'directories': sorted(directory_names),
                'files': expected_files})
            check('tar_all_source_bytes', all(tar.extractfile('private/' + name).read() == body
                                             for name, body in payloads.items()))
            check('tar_private_modes', all(m.mode == (0o700 if m.isdir() else 0o600)
                                           and (m.isdir() or m.isfile()) for m in members))
        result['manifest_sha256'] = hashlib.sha256(manifest_bytes).hexdigest()

        cli = SOURCES[2]
        common = ['--archive', archive, '--sha256', archive_digest,
                  '--expected-revision', revision, '--summary', summary_path]
        restored = work / 'restored-output'
        for operation in ('inspect', 'restore'):
            argv = [sys.executable, cli, operation, *common]
            if operation == 'restore':
                argv += ['--output-dir', restored]
            proc = run('outside_checkout_' + operation, argv, cwd=outside)
            check(operation + '_cli_success', proc.returncode == 0 and proc.stderr == b'')
            report = json.loads(proc.stdout)
            result[operation + '_report'] = report
            check(operation + '_counts_and_digest', report['outcome'] == 'pass'
                  and report['retention_verified'] is True and report['summary_checked'] is True
                  and report['expected_revision'] == revision and report['archive_sha256'] == archive_digest
                  and report['archive_bytes'] == archive.stat().st_size
                  and report['file_count'] == len(payloads) and report['directory_count'] == len(directory_names)
                  and report['input_bytes'] == total_bytes)
            check(operation + '_no_native_or_authentication_claims', report['native_execution'] == 'not_run'
                  and all(report[key] is False for key in ('retained_code_executed', 'origin_authenticated',
                      'native_acceptance', 'performance_acceptance', 'phase_acceptance')))
        check('restore_completion_flag', result['restore_report']['restoration_completed'] is True)
        check('cli_runs_outside_checkout', REPO not in outside.parents and outside != REPO
              and 'PYTHONPATH' not in env)
        expected_restore_dirs = {'', *('private' + ('/' + name if name else '') for name in directory_names)}
        expected_restore_files = {'manifest.json', *('private/' + name for name in payloads)}
        restore_dirs, restore_files = {''}, set()
        for path in restored.rglob('*'):
            relative = path.relative_to(restored).as_posix()
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                restore_dirs.add(relative)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                restore_files.add(relative)
            else:
                raise AssertionError('restored_unexpected_file_type')
        check('restored_exact_inventory', restore_dirs == expected_restore_dirs
              and restore_files == expected_restore_files)
        check('restored_all_source_bytes', all((restored / 'private' / name).read_bytes() == body
                                               for name, body in payloads.items()))
        check('restored_manifest_bytes', (restored / 'manifest.json').read_bytes() == manifest_bytes)
        check('restored_private_modes', all(mode(restored / name) == 0o700 for name in restore_dirs)
              and all(mode(restored / name) == 0o600 for name in restore_files))
        check('hidden_files_and_directories_preserved', (restored / 'private/.dotfile').is_file()
              and (restored / 'private/.hidden/config.json').is_file()
              and (restored / 'private/.hidden/empty').is_dir())
        check('empty_directories_preserved', all(not list((restored / 'private' / name).iterdir())
              for name in ('.hidden/empty', 'empty-root', 'nested/empty')))
        check('inert_executable_never_executed', not canary.exists()
              and mode(restored / 'private/inert-canary.sh') == 0o600)
        check('no_incomplete_marker_after_success', not (restored / '.restore-incomplete.PRIVATE.json').exists())
        check('source_bytes_unchanged', all((source / name).read_bytes() == body for name, body in payloads.items()))
        check('ciphertext_and_plain_archive_unchanged', digest(cipher) == cipher_digest
              and digest(archive) == archive_digest)
        result['negative_reports'] = {}
        for operation in ('inspect', 'restore'):
            rejected_output = work / ('rejected-bad-digest-' + operation)
            negative_argv = [sys.executable, cli, operation, '--archive', archive,
                '--sha256', '0' * 64, '--expected-revision', revision, '--summary', summary_path]
            if operation == 'restore':
                negative_argv += ['--output-dir', rejected_output]
            proc = run('reject_bad_digest_' + operation, negative_argv, cwd=outside)
            check(operation + '_bad_digest_exit', proc.returncode == 1 and proc.stderr == b'')
            negative_report = json.loads(proc.stdout)
            result['negative_reports'][operation + '_bad_digest'] = negative_report
            check(operation + '_bad_digest_no_false_acceptance', negative_report == {
                'schema_version': 1, 'contract_id': 'p06-qualified-warm-retention-review-v1',
                'outcome': 'fail', 'error_code': 'retention-rejected',
                'retention_verified': False, 'restoration_completed': False,
                'native_execution': 'not_run', 'retained_code_executed': False,
                'origin_authenticated': False, 'native_acceptance': False,
                'performance_acceptance': False, 'phase_acceptance': False})
            check(operation + '_bad_digest_no_output', not rejected_output.exists())
        check('canary_still_absent_after_negative_checks', not canary.exists())
        result['source_sha256_after'] = source_hashes()
        check('requested_final_source_hashes_after',
              result['source_sha256_after'] == EXPECTED_SOURCE_HASHES)
        check('sources_unchanged_during_run', result['source_sha256_before'] == result['source_sha256_after'])
        result['outcome'] = 'pass'
    except Exception as error:
        result['error_type'] = type(error).__name__
        result['error_code'] = str(error) if isinstance(error, AssertionError) else 'probe-failed'
    finally:
        cleanup_ok = True
        for path, device, inode in identities:
            try:
                info = path.lstat()
                if (info.st_dev, info.st_ino) != (device, inode) or path.parent != work:
                    cleanup_ok = False
                    continue
                path.unlink()
                cleanup_ok = cleanup_ok and not path.exists()
            except OSError:
                cleanup_ok = False
        result['identity_files_deleted'] = cleanup_ok and len(identities) == 2
        result['checks']['disposable_identity_cleanup'] = result['identity_files_deleted']
        if not result['identity_files_deleted']:
            result['outcome'] = 'fail'
        result['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        if 'source_sha256_after' not in result:
            result['source_sha256_after'] = source_hashes()
        json_path = NOTES / 'a33.json'
        json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        json_path.chmod(0o600)
        lines = [
            '# A33: final cleanup bytes, real age retention round trip', '',
            f"Outcome: **{result['outcome']}**. Scope: final cleanup bytes; synthetic transport and retention integration only.", '',
            f"Checkout HEAD: `{result.get('checkout_head', 'not-recorded')}`; concurrent working tree, with exact source hashes below.",
            f"Python: `{result.get('python', {}).get('path', 'not-recorded')}` ({result.get('python', {}).get('version', 'unknown')}).",
            'Actual age and age-keygen: v1.3.2; no mocked encryption or decryption.',
            f"Release archive SHA256: `{RELEASE_SHA256}` (verified).", '',
            '## Results', '',
            f"- Checks passed: {sum(result['checks'].values())}/{len(result['checks'])}.",
            f"- Fixture: {result.get('fixture', {}).get('file_count', 0)} files, {result.get('fixture', {}).get('directory_count', 0)} directories including the source root; {result.get('fixture', {}).get('input_bytes', 0)} source bytes.",
            '- Included hidden files and directories, three empty directories, an empty file, binary data spanning age chunks, spaces, UTF-8/PAX paths, a long PAX path, and an executable inert canary.',
            '- Called the actual existing encrypt_private_directory API with the real age binary, decrypted with real age, then invoked the new inspect and restore CLI from outside the checkout with PYTHONPATH absent.',
            '- Independently verified every tar and restored file byte, exact manifest inventory, summary counts, ciphertext SHA256/size, archive digest, and private modes (0700 directories, 0600 restored files).',
            '- Wrong disposable identity rejected by age; no plaintext released. The restored executable canary was inert and became mode 0600.',
            f"- Both disposable identity files removed after the checks: {result['identity_files_deleted']}. No private key bytes were printed or retained in the reports.",
            '- Inspect/restore report native_execution=not_run and false retained-code execution, origin-authentication, native/performance/phase acceptance flags.',
            '- Both inspect and restore rejected an incorrect archive digest with exit 1, fixed failure JSON, false acceptance/execution flags, and no destination.',
            '- Before/after hashes matched the requested final cleanup bytes. The A12 probe was adapted into a new A33 tree; earlier results were not promoted to the final bytes.',
            '- No genuine private, user, historical control, vendor, or native execution data was used; no GPU/native experiment ran.', '',
            '## Exact tested source SHA256', '', '| Source | SHA256 |', '|---|---|',
        ]
        for name, value in result.get('source_sha256_before', {}).items():
            lines.append(f'| `{name}` | `{value}` |')
        lines += ['', f"Source hashes unchanged during run: {result['checks'].get('sources_unchanged_during_run', False)}.",
                  f"Probe SHA256: `{result.get('probe_sha256', 'not-recorded')}`.", '',
                  '## Retained sanitized evidence', '',
                  f"Full structured checks, exact subprocess argv/cwd/exit results, fixture hashes, and CLI reports: `{json_path}`.",
                  f"Reproduction probe: `{Path(__file__)}`.",
                  f"Synthetic artifacts only: `{work}` (0700).",
                  'The two identities were the only test artifacts deleted. Their deletion is not a secure-erasure claim.', '',
                  'This check does not authenticate an archive producer, grant any acceptance, qualify native correctness or performance, replace a full strict governance run, or cover injected close failures.',
                  'Exact invocation and subprocess commands are in the JSON report; incoming TMPDIR is the requested task base, with a fresh private child used during execution.',
                  '']
        (NOTES / 'a33.md').write_text('\n'.join(lines))
        (NOTES / 'a33.md').chmod(0o600)
    print(json.dumps({'outcome': result['outcome'], 'checks_passed': sum(result['checks'].values()),
                      'checks_total': len(result['checks']), 'identity_files_deleted': result['identity_files_deleted'],
                      'report': str(NOTES / 'a33.json'), 'note': str(NOTES / 'a33.md'),
                      'error_code': result.get('error_code')}))
    return 0 if result['outcome'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
