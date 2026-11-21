#!/usr/bin/env python3
"""Copy-only W07 A3 adversarial probes; never import or run retained package binaries."""
import argparse
import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import time
import zipfile

BASE = Path('/workspace/scratch/ba0248fde989')
SOURCE = BASE / 'AI-GPU'
ORIGINAL = BASE / 'p05-work/ci-e1420fd'
DIST = 'vortex_ai-0.1.0.dist-info/'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def raw_json(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def inventory(root):
    return {p.relative_to(root).as_posix(): {'sha256': sha(p.read_bytes()), 'size_bytes': p.stat().st_size}
            for p in sorted(root.rglob('*')) if p.is_file()}


def descriptor(path, raw):
    return {'path': path, 'sha256': sha(raw), 'size_bytes': len(raw)}


def replace_descriptor(report, path, raw):
    def walk(value):
        if isinstance(value, dict):
            if value.get('path') == path and 'sha256' in value:
                value['sha256'] = sha(raw)
                if 'size_bytes' in value:
                    value['size_bytes'] = len(raw)
                if 'size' in value:
                    value['size'] = len(raw)
            for key, child in value.items():
                if key != "native_input":
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(report)


def write_bound(root, report, name, raw):
    (root / name).write_bytes(raw)
    replace_descriptor(report, name, raw)


def mutate_snapshot(root, report, key, function):
    name = report[key]['path']
    value = json.loads((root / name).read_bytes())
    function(value)
    write_bound(root, report, name, raw_json(value))


def mutate_native(root, report, function):
    path = root / 'native/report.json'
    native = json.loads(path.read_bytes())
    function(native)
    raw = raw_json(native)
    path.write_bytes(raw)
    replace_descriptor(report, 'native/report.json', raw)
    for row in report['native_input']['files']:
        if row['path'] == 'report.json':
            row.update(descriptor('report.json', raw))


def append_log(root, report, name, line):
    row = next(row for row in report['commands'] if row['id'] == name)
    path = root / row['log']
    raw = path.read_bytes() + line
    path.write_bytes(raw)
    row['log_sha256'], row['log_size_bytes'] = sha(raw), len(raw)


def record(files):
    name = DIST + 'RECORD'
    rows = []
    for path, raw in sorted(files.items()):
        if path != name:
            rows.append([path, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='), str(len(raw))])
    rows.append([name, '', ''])
    out = io.StringIO(newline='')
    csv.writer(out, lineterminator='\n').writerows(rows)
    return out.getvalue().encode()


def rewrite_wheel(root, report, mutate, *, repair_record=True):
    row = next(row for row in report['packages'] if row['path'].endswith('.whl'))
    path = root / row['path']
    with zipfile.ZipFile(path) as stream:
        files = {name: stream.read(name) for name in stream.namelist()}
    mutate(files)
    if repair_record:
        files[DIST + 'RECORD'] = record(files)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as stream:
        for name, raw in files.items():
            info = zipfile.ZipInfo(name, (2026, 11, 21, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            stream.writestr(info, raw)
    row.update(descriptor(row['path'], path.read_bytes()))
    value = [descriptor(name, raw) for name, raw in sorted(files.items())]
    write_bound(root, report, report['wheel_inventory']['path'], raw_json(value))
    installed_root = root / 'artifacts/installed'
    extras = {name: (installed_root / name).read_bytes() for name in
              (DIST + 'INSTALLER', DIST + 'REQUESTED', DIST + 'direct_url.json')}
    direct = json.loads(extras[DIST + 'direct_url.json'])
    direct['archive_info'] = {'hash': 'sha256=' + row['sha256'], 'hashes': {'sha256': row['sha256']}}
    extras[DIST + 'direct_url.json'] = raw_json(direct)
    installed = dict(files, **extras)
    installed[DIST + 'RECORD'] = record(installed)
    shutil.rmtree(installed_root)
    installed_root.mkdir()
    for name, raw in installed.items():
        target = installed_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    value = [descriptor(name, raw) for name, raw in sorted(installed.items())]
    for key in ('installed_before', 'installed_after'):
        write_bound(root, report, report[key]['path'], raw_json(value))


def rewrite_sdist(root, report, mutate):
    row = next(row for row in report['packages'] if row['path'].endswith('.tar.gz'))
    path = root / row['path']
    with tarfile.open(path, 'r:gz') as stream:
        members = [(item, stream.extractfile(item).read() if item.isfile() else None) for item in stream]
    mutate(members)
    with tarfile.open(path, 'w:gz') as stream:
        for item, raw in members:
            if raw is not None:
                item.size = len(raw)
            stream.addfile(item, io.BytesIO(raw) if raw is not None else None)
    row.update(descriptor(row['path'], path.read_bytes()))


def command_field(key, value, name='package-create-venv'):
    def mutate(root, report):
        next(row for row in report['commands'] if row['id'] == name)[key] = value
    return mutate


def source_body(root, report):
    name = 'artifacts/source/python/vortex_ai/_api.py'
    write_bound(root, report, name, (root / name).read_bytes() + b'\n# counterfeit retained body\n')


def foreign_path(root, report):
    def change(value):
        for row in value['commands']:
            row['environment']['PATH'] = '/tmp/unrecorded-tools:/usr/bin:/bin'
    change(report)
    mutate_native(root, report, change)


def wheel_elf_machine(files):
    name = next(name for name in files if name.endswith('.so'))
    raw = bytearray(files[name]); struct.pack_into('<H', raw, 18, 183); files[name] = bytes(raw)


def wheel_false_pin(files):
    name = next(name for name in files if name.endswith('.so'))
    # Literal package source pin, visible in the retained manifest and compiled image.
    manifest = json.loads((ORIGINAL / 'simx-fp16/python/artifacts/bundle/manifest.json').read_bytes())
    pin = manifest['binding_source_sha256'].encode() + b'\0'
    assert pin in files[name]
    files[name] = files[name].replace(pin, b'0' * 64 + b'\0')


def tar_link(members):
    item = tarfile.TarInfo('vortex_ai-0.1.0/unexpected-link')
    item.type = tarfile.SYMTYPE; item.linkname = '/tmp/foreign'
    members.append((item, None))


def tar_traversal(members):
    item = tarfile.TarInfo('vortex_ai-0.1.0/../../escaped')
    members.append((item, b'counterfeit'))


def tar_duplicate(members):
    item, raw = next((i, r) for i, r in members if i.isfile())
    members.append((item, raw))


def tar_source(members):
    for index, (item, raw) in enumerate(members):
        if item.name == 'vortex_ai-0.1.0/setup.py':
            members[index] = item, raw + b'\n# wrong setup body\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--auditor', type=Path, default=SOURCE / 'docs/project/evidence/p05-python/reviews/audit_provenance.py')
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=False)
    before = {fmt: inventory(ORIGINAL / ('simx-' + fmt) / 'python') for fmt in ('fp16', 'bf16')}
    zip_before = {fmt: sha((ORIGINAL / ('simx-' + fmt + '.zip')).read_bytes()) for fmt in ('fp16', 'bf16')}
    auditor_raw = args.auditor.read_bytes()
    (args.run_dir / 'auditor.py').write_bytes(auditor_raw)
    spec = importlib.util.spec_from_file_location('provenance_under_review', args.auditor)
    auditor = importlib.util.module_from_spec(spec); spec.loader.exec_module(auditor)
    git = auditor.Git(SOURCE)
    cases = [
        ('selected-positive', lambda p, r: None, True),
        ('retained-source-rehashed', source_body, False),
        ('tool-identity-drift', lambda p, r: mutate_snapshot(p, r, 'tools_after', lambda d: d['gcc'].update(sha256='0' * 64)), False),
        ('bundle-extra-file', lambda p, r: (p / 'artifacts/bundle/extra.bin').write_bytes(b'extra'), False),
        ('bundle-symlink', lambda p, r: (p / 'artifacts/bundle/extra-link').symlink_to('/tmp/absent'), False),
        ('command-not-started', command_field('process_started', False), False),
        ('command-nonzero', command_field('exit_code', 1), False),
        ('command-no-cleanup', command_field('cleanup_complete', False), False),
        ('command-duration-after-timeout', command_field('duration_seconds', 4000), False),
        ('command-timeout-exceeds-fixed-contract', command_field('timeout_seconds', 7000), False),
        ('command-log-raw-failure', lambda p, r: append_log(p, r, 'package-create-venv', b'P05_FAILURE {"error":"failed"}\n'), False),
        ('command-path-foreign-directory', foreign_path, False),
        ('native-initial-resource-insufficient', lambda p, r: mutate_native(p, r, lambda n: n['resources_before'].update(available_memory_bytes=0)), False),
        ('native-budget-zero-memory', lambda p, r: mutate_native(p, r, lambda n: n['budget'].update(max_rss_bytes=0)), False),
        ('native-log-descriptor-corrupt', lambda p, r: mutate_native(p, r, lambda n: n['commands'][0].update(log_sha256='0' * 64)), False),
        ('sdist-traversal', lambda p, r: rewrite_sdist(p, r, tar_traversal), False),
        ('sdist-link', lambda p, r: rewrite_sdist(p, r, tar_link), False),
        ('sdist-duplicate', lambda p, r: rewrite_sdist(p, r, tar_duplicate), False),
        ('sdist-source-rehashed', lambda p, r: rewrite_sdist(p, r, tar_source), False),
        ('wheel-python-source-rehashed', lambda p, r: rewrite_wheel(p, r, lambda f: f.update({'vortex_ai/_api.py': f['vortex_ai/_api.py'] + b'\n# wrong source\n'})), False),
        ('wheel-requires-dist-rehashed', lambda p, r: rewrite_wheel(p, r, lambda f: f.update({DIST + 'METADATA': f[DIST + 'METADATA'].replace(b'Name: vortex-ai\n', b'Name: vortex-ai\nRequires-Dist: numpy\n')})), False),
        ('wheel-elf-machine-rehashed', lambda p, r: rewrite_wheel(p, r, wheel_elf_machine), False),
        ('wheel-compiled-pin-rehashed', lambda p, r: rewrite_wheel(p, r, wheel_false_pin), False),
        ('wheel-record-corrupt', lambda p, r: rewrite_wheel(p, r, lambda f: f.update({DIST + 'RECORD': f[DIST + 'RECORD'].replace(b'sha256=', b'sha512=', 1)}), repair_record=False), False),
        ('installed-inventory-drift', lambda p, r: mutate_snapshot(p, r, 'installed_after', lambda d: d[0].update(sha256='0' * 64)), False),
        ('observed-install-source-root', lambda p, r: mutate_snapshot(p, r, 'observations', lambda d: d['installation'].update(package_file=r['paths']['source'] + '/python/vortex_ai/__init__.py')), False),
    ]
    results = []
    for name, mutate, expected in cases:
        root = args.run_dir / name
        shutil.copytree(ORIGINAL / 'simx-fp16/python', root)
        report = json.loads((root / 'report.json').read_bytes())
        mutate(root, report)
        (root / 'report.json').write_bytes(raw_json(report))
        start = time.monotonic()
        try:
            value = auditor.audit_packet(root, git)
            actual, reason = True, None
            result = {'outcome': 'pass', 'packet_evidence': value}
        except Exception as error:
            actual, reason = False, type(error).__name__ + ': ' + str(error)
            result = {'outcome': 'fail', 'reason': reason}
        result.update(case=name, expected_pass=expected, actual_pass=actual, expected_met=actual == expected,
                      elapsed_seconds=round(time.monotonic() - start, 6), auditor_sha256=sha(auditor_raw))
        output = args.run_dir / (name + '.json'); output.write_bytes(raw_json(result))
        results.append({k: v for k, v in result.items() if k != 'packet_evidence'} | {'output_sha256': sha(output.read_bytes())})
        print(json.dumps(results[-1]), flush=True)
    after = {fmt: inventory(ORIGINAL / ('simx-' + fmt) / 'python') for fmt in ('fp16', 'bf16')}
    zip_after = {fmt: sha((ORIGINAL / ('simx-' + fmt + '.zip')).read_bytes()) for fmt in ('fp16', 'bf16')}
    receipt = {'auditor_path': str(args.auditor), 'auditor_initial_sha256': sha(auditor_raw),
               'auditor_final_sha256': sha(args.auditor.read_bytes()), 'cases': results,
               'checks': len(results), 'expected_met': sum(row['expected_met'] for row in results),
               'original_member_inventories_unchanged': before == after, 'original_zip_hashes_unchanged': zip_before == zip_after,
               'original_members': {fmt: len(rows) for fmt, rows in before.items()}, 'original_zip_sha256': zip_before,
               'original_inventory_sha256': {fmt: sha(raw_json(rows)) for fmt, rows in before.items()}}
    (args.run_dir / 'probe-results.json').write_bytes(raw_json(receipt))
    print(json.dumps({k: v for k, v in receipt.items() if k != 'cases'}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
