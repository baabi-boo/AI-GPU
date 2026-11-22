from pathlib import Path
import difflib
import json
import shlex
import subprocess
import tempfile

SOURCE = Path('/workspace/scratch/98908dfa3444/AI-GPU')
OUT = Path('/workspace/scratch/98908dfa3444')
LOG = OUT / 'w03-public-build-validation.log'


def run(argv, cwd):
    result = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=60)
    with LOG.open('a') as log:
        log.write('$ ' + shlex.join(argv) + '\n' + result.stdout
                  + '\nexit=' + str(result.returncode) + '\n')
    if result.returncode:
        raise RuntimeError(result.stdout[-8000:])
    return result.stdout


def compile_flags(words):
    result = []
    i = 1
    while i < len(words):
        if words[i] in ('-c', '-o', '-MF'):
            i += 2
        elif words[i] in ('-MMD', '-MP'):
            i += 1
        else:
            result.append(words[i])
            i += 1
    return result


def normalize_flags(flags, cwd):
    return [('-I' + str((cwd / flag[2:]).resolve())) if flag.startswith('-I')
            else flag for flag in flags]


with tempfile.TemporaryDirectory(prefix='counter-public-build-') as temporary:
    root = Path(temporary)
    build = root / 'checked'
    build.mkdir()
    run([str(SOURCE / 'configure'), '--xlen=64', '--profile=p02-tfr',
         '--osversion=ubuntu/focal', f'--tooldir={root / "unused-tools"}'], build)
    unit = build / 'sim/simx'
    fragment = build / 'tests/unittest/checked_counters/public.mk'
    assert fragment.read_bytes() == (SOURCE / 'tests/unittest/checked_counters/public.mk').read_bytes()
    base = ['make', '--no-print-directory', 'PERF=1', 'PROFILE=p02-tfr',
            'CXX=/usr/bin/g++', 'CONFIGS=-DSIMX_CHECKED_COUNTERS=1']
    make = [*base, '-f', str(fragment)]
    transcript = run([*make, '-n', 'checked-public'], unit)
    (OUT / 'w03-public-build-compiler-records.log').write_text(transcript)
    records = [shlex.split(line.replace('\\\n', ' '))
               for line in transcript.replace('\\\n', ' ').splitlines()
               if line.startswith('/usr/bin/g++ ')]
    compiles = [record for record in records if '-c' in record]
    links = [record for record in records if '-c' not in record]
    assert len(compiles) == 63, len(compiles)
    assert len(links) == 4, len(links)
    assert all('-fno-access-control' not in record for record in records)
    by_source = {}
    by_target = {}
    for record in compiles:
        source = record[record.index('-c') + 1]
        target = record[record.index('-o') + 1]
        by_source.setdefault(source, []).append(record)
        assert target not in by_target
        by_target[target] = record
    links_by_name = {Path(record[record.index('-o') + 1]).name: record for record in links}
    model = links_by_name['libchecked-simx.so']
    objects = [word for word in model if word.endswith('.o')]
    assert len(objects) == 44 and len(set(objects)) == 44
    originals = ['socket.o', 'mem/cache.o', 'mem/memory.o', 'tcu/tcu_tbuf.o',
                 'tests/checked_counters_test.o', 'tests/checked_counters/public_hooks.o']
    assert all(str(unit / 'obj' / path) not in objects for path in originals)
    first = run([*base, '-f', 'checked_counters.mk', '-n',
                 str(unit / 'checked_counters_test')], unit)
    (OUT / 'w03-public-first-build-dry-run.log').write_text(first)
    first_records = [shlex.split(line) for line in first.splitlines()
                     if line.startswith('/usr/bin/g++ ')]
    assert len([record for record in first_records if '-c' in record]) == 45
    prior_object_options = [word for path in objects for word in ('-o', path)]
    second = run([*make, *prior_object_options, '-n', 'checked-public'], unit)
    (OUT / 'w03-public-second-build-dry-run.log').write_text(second)
    second_records = [shlex.split(line) for line in second.replace('\\\n', ' ').splitlines()
                      if line.startswith('/usr/bin/g++ ')]
    assert len([record for record in second_records if '-c' in record]) == 19
    assert len([record for record in second_records if '-c' not in record]) == 4
    wraps = ['_ZN6vortex9ProcessorC1Ev', '_ZN6vortex9ProcessorD1Ev',
             '_ZN6vortex9Processor11run_checkedEv', '_ZN6vortex9Processor8dcr_readEjjPj',
             '_ZN6vortex9Processor9dcr_writeEjj']
    backend = links_by_name['libvortex-simx.so']
    assert [word for word in backend if word.startswith('-Wl,--wrap=')] == [
        '-Wl,--wrap=' + name for name in wraps]
    assert len([word for word in backend if word.endswith('.o')]) == 4
    runtime = links_by_name['libvortex.so']
    assert len([word for word in runtime if word.endswith('.o')]) == 14
    assert all(not any(word.startswith('-Wl,--wrap=') for word in record)
               for record in links if record is not backend)
    hook = by_source[str(SOURCE / 'tests/unittest/checked_counters/public_hooks.cpp')][0]
    core = by_source[str(SOURCE / 'sim/simx/core.cpp')][0]
    assert compile_flags(hook) == compile_flags(core)
    for kind, source in [('runtime', SOURCE / 'sw/runtime/stub/vortex.cpp'),
                         ('backend', SOURCE / 'sw/runtime/simx/vortex.cpp')]:
        normal_cwd = build / ('sw/runtime/stub' if kind == 'runtime' else 'sw/runtime/simx')
        normal = run([*base, '-n', 'all'], normal_cwd)
        normal_records = [shlex.split(line) for line in normal.splitlines()
                          if line.startswith('/usr/bin/g++ ') and str(source) in line]
        assert len(normal_records) == 1
        normal_record = normal_records[0]
        expected = normalize_flags(normal_record[1:normal_record.index(str(source))], normal_cwd)
        actual = normalize_flags(compile_flags(by_source[str(source)][0]), unit)
        assert actual == expected, '\n'.join(difflib.unified_diff(expected, actual))
    for name in ('runtime_config.stamp', 'backend_config.stamp', 'main_config.stamp'):
        stamp = unit / 'checked-public' / name
        run([*make, str(stamp)], unit)
        (OUT / ('w03-public-' + name)).write_bytes(stamp.read_bytes())
    for source in ('sw/runtime/stub/vortex.cpp', 'sw/runtime/simx/vortex.cpp',
                   'sw/runtime/common/utils.cpp', 'sim/common/cmd_processor.cpp'):
        for record in by_source[str(SOURCE / source)]:
            if '/checked-public/obj/' not in record[record.index('-o') + 1]:
                continue
            run(['/usr/bin/g++', *compile_flags(record), '-fsyntax-only',
                 str(SOURCE / source)], unit)
    bad = subprocess.run([*base[:-1], 'CONFIGS=', '-f', str(fragment), '-n', 'checked-public'],
                         cwd=unit, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert bad.returncode and 'requires CONFIGS' in bad.stdout
    result = {'fresh_compile_records': len(compiles), 'model_objects': len(objects),
              'links': len(links), 'runtime_objects': 14, 'backend_objects': 4,
              'same_model_hook_flags': True, 'same_normal_runtime_flags': True,
              'same_normal_backend_flags': True, 'wrapped_processor_symbols': wraps,
              'ordinary_build_rejected': True, 'native_link_run': 'not_run'}
    (OUT / 'w03-public-build-results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
