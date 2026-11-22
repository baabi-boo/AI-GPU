import ast
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path('/workspace/scratch/98908dfa3444/AI-GPU')
SCRATCH = ROOT.parent
OUT = ROOT / 'docs/project/evidence/p06-counter-diagnostics'
OUT.mkdir(parents=True, exist_ok=True)
BOUND = '407ab9fea5e4f793a2a5088f566a87f3e631aa84'
BASE = '7455e008c1e001d3329e74fd55ffcd942592ec5f'
PUBLIC = '81ed6871634fefbf5c78fb27cf10dce913bd4d9c'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def save(name, value):
    path = OUT / name
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n')
    return path

dep_metadata = json.loads((SCRATCH / 'w01-ramulator-manifest.json').read_text())
dep_sources = json.loads((SCRATCH / 'w01-ramulator-sources.json').read_text())
assert dep_metadata['revision'] == dep_sources['revision'] == 'e62c84a6f0e06566ba6e182d308434b4532068a5'
original = {f['path']: f for f in dep_sources['files']}
roles = {
    'src/base/base.h': ('selected infrastructure', ['Implementation::finalize', 'Implementation::print_stats', 'gather_components']),
    'src/base/factory.cpp': ('selected infrastructure', ['Factory::create_frontend', 'Factory::create_memory_system']),
    'src/base/stats.h': ('statistics emission', ['StatWrapper::emit_to']),
    'src/base/stats.cpp': ('statistics emission', ['operator<<(YAML::Emitter&, const Stats&)']),
    'src/frontend/frontend.h': ('selected interface', ['IFrontEnd::finalize']),
    'src/frontend/impl/external_wrapper/gem5_frontend.cpp': ('selected GEM5 frontend', ['GEM5::init', 'GEM5::tick', 'GEM5::receive_external_requests']),
    'src/memory_system/memory_system.h': ('selected interface', ['IMemorySystem::finalize']),
    'src/memory_system/impl/generic_DRAM_system.cpp': ('selected GenericDRAM memory system', ['GenericDRAMSystem::init', 'GenericDRAMSystem::tick']),
    'src/dram_controller/controller.h': ('selected interface', ['IDRAMController']),
    'src/dram_controller/refresh.h': ('selected interface', ['IRefreshManager']),
    'src/dram_controller/scheduler.h': ('selected interface', ['IScheduler']),
    'src/dram_controller/rowpolicy.h': ('selected interface', ['IRowPolicy']),
    'src/dram/dram.h': ('selected interface', ['IDRAM::finalize']),
    'src/addr_mapper/addr_mapper.h': ('selected interface', ['IAddrMapper']),
    'src/dram_controller/impl/generic_dram_controller.cpp': ('selected Generic controller', ['GenericDRAMController::finalize', 'GenericDRAMController::tick', 'GenericDRAMController::serve_completed_reads']),
    'src/dram_controller/impl/refresh/all_bank_refresh.cpp': ('selected AllBank refresh manager', ['AllBankRefresh']),
    'src/dram_controller/impl/rowpolicy/basic_rowpolicies.cpp': ('selected OpenRowPolicy', ['OpenRowPolicy']),
    'src/dram_controller/impl/scheduler/generic_scheduler.cpp': ('selected FRFCFS scheduler', ['FRFCFS']),
    'src/addr_mapper/impl/linear_mappers.cpp': ('selected RoBaRaCoCh address mapper', ['RoBaRaCoCh']),
    'src/dram/impl/HBM2.cpp': ('selected HBM2 device', ['HBM2']),
    'src/dram_controller/impl/plugin/trace_recorder.cpp': ('audited optional plugin; excluded from bound route', ['TraceRecorder']),
}
dep_files = []
for row in dep_metadata['files']:
    source = original[row['path']]
    raw = source['content'].encode('utf-8')
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert blob == source['git_blob'] == row['git_blob']
    assert sha(raw) == row['sha256'] and len(raw) == row['size_bytes']
    role, symbols = roles[row['path']]
    dep_files.append(dict(row, role=role, relevant_symbols=symbols,
                          original_utf8_blob_sha1_verified=True,
                          original_utf8_sha256_verified=True))
assert len(dep_files) == len(original) == len(roles) == 21
dependency = {
    'schema_version': 1,
    'contract': 'simx-counter-lifetime-dependency-source-v1',
    'evidence_kind': 'conditional-source-analysis',
    'repository': dep_metadata['repository'],
    'revision': dep_metadata['revision'],
    'gitlink': {'repository_path': 'third_party/ramulator', 'source_revision': BOUND,
                'revision': dep_metadata['revision']},
    'source_digest_method': 'SHA-256 of original UTF-8 bytes, preserving CRLF; Git SHA-1 of blob header plus those exact bytes',
    'source_acquisition': 'Original source bodies retained in the audit workspace and matched to the 21 supplied pinned Git blob IDs; this manifest retains identities and immutable upstream URLs.',
    'selected_graph': {
        'frontend': 'GEM5', 'memory_system': 'GenericDRAM', 'dram': 'HBM2',
        'controller': 'Generic', 'scheduler': 'FRFCFS', 'refresh_manager': 'AllBank',
        'row_policy': 'OpenRowPolicy', 'address_mapper': 'RoBaRaCoCh',
        'controller_plugins': [], 'gpu_memory_channels': 2,
        'per_adapter_channel_dram_channels': 1,
        'environment_requirements': {'VORTEX_DRAM_MODEL': 'absent (default Ramulator)', 'DRAM_TRACE': 'absent'},
    },
    'finalization_argument': [
        'Factory gathers the selected implementation children; interface finalizers traverse those children and print statistics.',
        'GEM5 creates no children and has empty init/tick with no finalize override.',
        'GenericDRAM creates HBM2, RoBaRaCoCh and Generic controller children; Generic creates FRFCFS, AllBank and OpenRowPolicy children.',
        'The Generic controller finalize override calculates five average statistics; the other selected concrete children use empty finalization, including IDRAM::finalize for HBM2.',
        'The selected print_stats path emits registered scalar/vector values and recursively visits children; it does not advance time, send a request or invoke request callbacks.',
        'The Generic controller request callback site is serve_completed_reads, reached from tick, not finalize.',
        'The SimX adapter dependency callback only appends to its response queue. Invoking the GPU response callback requires adapter drain, called from adapter tick.',
        'RamulatorDram destruction calls the two interface finalizers without tick, drain or send_request; the raw frontend/memory-system pointers are not deleted on that path.',
    ],
    'adapter_binding': {'path': 'sim/common/dram_sim.cpp', 'sha256': sha((ROOT / 'sim/common/dram_sim.cpp').read_bytes()),
                        'source_revision': BOUND,
                        'symbols': ['RamulatorDram::channel_config', 'RamulatorDram::issue', 'RamulatorDram::drain', 'RamulatorDram::tick', 'RamulatorDram::~RamulatorDram']},
    'excluded_routes': ['VORTEX_DRAM_MODEL=bank', 'GDDR6', 'HBM3', 'TraceRecorder enabled through DRAM_TRACE', 'replacement factories or plugins', 'unbound dependency binary'],
    'files': dep_files,
    'dependency_binary_source_attestation': False,
    'binary_provenance_limit': 'A cached library hash identifies bytes. It does not establish that those bytes were compiled from this revision or these source files. Application of the argument to an executable remains conditional on the actual loaded dependency implementing this graph and finalizer behavior.',
    'limitations': ['Source analysis is not a complete dependency correctness or memory-leak proof.', 'The absence of a tick or callback in finalization does not prove the preceding workload completed; quiescence is a separate premise.', 'This file is not a source-to-binary or toolchain attestation, native test result, RTL parity result, or hardware result.'],
    'qualified': False, 'ready_for_warm': False,
}
dep_path = save('dependency-source-manifest.json', dependency)

production = '''sim/common/perf_counter.h sim/common/simobject.h sim/common/dram_sim.cpp sim/common/dram_sim.h sim/common/cmd_processor.cpp sim/common/cmd_processor.h sim/common/mem.cpp sim/common/mem.h sim/simx/core.cpp sim/simx/core.h sim/simx/csr_unit.cpp sim/simx/lsu_unit.cpp sim/simx/processor.cpp sim/simx/processor_impl.h sim/simx/processor.h sim/simx/socket.cpp sim/simx/cluster.cpp sim/simx/types.h sim/simx/constants.h sim/simx/mem/cache.cpp sim/simx/mem/cache.h sim/simx/mem/cache_cluster.cpp sim/simx/mem/local_mem.cpp sim/simx/mem/local_mem.h sim/simx/mem/mem_coalescer.cpp sim/simx/mem/mem_coalescer.h sim/simx/mem/memory.cpp sim/simx/mem/memory.h sim/simx/tcu/tcu_unit.cpp sim/simx/tcu/tcu_unit.h sim/simx/tcu/tcu_tbuf.cpp sim/simx/tcu/tcu_tbuf.h sw/runtime/common/async_run.h sw/runtime/common/device.cpp sw/runtime/common/queue.cpp sw/runtime/common/buffer.cpp sw/runtime/common/module.cpp sw/runtime/common/perf.cpp sw/runtime/common/vortex2_internal.h sw/runtime/common/callbacks.h sw/runtime/simx/vortex.cpp sw/runtime/ai/runtime.cpp VX_config.toml VX_types.toml'''.split()
support = '''ci/project/p06_contract.py tests/unittest/checked_counters/counter_access.h tests/unittest/checked_counters/counter_access.cpp tests/unittest/checked_counters/access_cache.cpp tests/unittest/checked_counters/access_memory.cpp tests/unittest/checked_counters/access_socket.cpp tests/unittest/checked_counters/access_tcu.cpp tests/unittest/checked_counters/main.cpp tests/regression/ai_warm_workspace/main.cpp tests/regression/ai_warm_workspace/observer.cpp'''.split()
production.append('sw/runtime/common/callbacks.inc')
files = []
for path in production + support:
    data = (ROOT / path).read_bytes()
    assert data == git('show', BOUND + ':' + path), path
    previous = subprocess.run(['git', '-C', str(ROOT), 'show', BASE + ':' + path], capture_output=True)
    same_base = previous.returncode == 0 and data == previous.stdout
    if path in production:
        assert same_base, path
    files.append({'path': path, 'role': 'production-source' if path in production else 'inventory-or-caller-evidence',
                  'sha256': sha(data), 'size_bytes': len(data),
                  'git_blob': git('rev-parse', BOUND + ':' + path).decode().strip(),
                  'unchanged_from_audited_base': same_base})

tree = ast.parse((ROOT / 'ci/project/p06_contract.py').read_text())
counters = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_COUNTERS' for t in n.targets))
core_fields = dict(zip([r[0] for r in counters[:13]], ['cycles','instrs','sched_idle','active_warps','stalled_warps','issued_warps','issued_threads','scrb_stalls','lsu_stalls','tcu_stalls','tcu_instrs','loads','stores']))
cache_fields = {'reads': 'reads', 'writes': 'writes', 'miss_r': 'read_misses', 'miss_w': 'write_misses', 'evicts': 'evictions', 'mshr_st': 'mshr_stalls'}
selectors = []
excluded = []
for name, cls, csr, cid, scope, unit, cap, cls_macro, csr_macro in counters:
    if name.startswith(('l2cache_', 'l3cache_')):
        excluded.append({'name': name, 'mpm_class': cls, 'csr': csr, 'core_id': cid, 'reason': 'cache capability disabled; do not query'})
        continue
    if name in core_fields:
        components = ['Core::Impl::perf_stats_.' + core_fields[name]]
        sources = ['sim/simx/core.h', 'sim/simx/core.cpp']
        if name in ('core_loads', 'core_stores'): sources += ['sim/simx/lsu_unit.cpp']
        aggregation = 'single cumulative component'
    elif name.startswith(('icache_', 'dcache_')):
        prefix, field = name.split('_', 1)
        components = [f'{prefix}.CacheBank[{i}]::perf_stats_.{cache_fields[field]}' for i in range(1 if prefix == 'icache' else 2)]
        sources = ['sim/simx/mem/cache.h', 'sim/simx/mem/cache.cpp', 'sim/simx/mem/cache_cluster.cpp', 'sim/simx/socket.cpp']
        aggregation = 'zero-initialized checked Cache::PerfStats::operator+= at bank, cluster and socket readout'
    elif name.startswith('lmem_'):
        components = ['LocalMem::Impl::perf_stats_.' + {'lmem_reads':'reads','lmem_writes':'writes','lmem_bank_st':'bank_stalls'}[name]]
        sources = ['sim/simx/mem/local_mem.h', 'sim/simx/mem/local_mem.cpp']
        aggregation = 'single cumulative component'
    elif name == 'coalescer_miss':
        components = ['MemCoalescer[0]::perf_stats_.misses']
        sources = ['sim/simx/mem/mem_coalescer.h', 'sim/simx/mem/mem_coalescer.cpp', 'sim/simx/csr_unit.cpp']
        aggregation = 'zero-initialized checked PerfCounter sum over exactly one LSU block'
    elif name in ('memory_reads', 'memory_writes', 'memory_lt'):
        components = ['ProcessorImpl::perf_mem_' + {'memory_reads':'reads_', 'memory_writes':'writes_', 'memory_lt':'latency_'}[name]]
        sources = ['sim/simx/processor_impl.h', 'sim/simx/processor.cpp']
        aggregation = 'single cumulative component; latency adds the checked pending-read balance in run/cycle loops'
    elif name == 'memory_bank_st':
        components = ['Memory::Impl::mem_xbar_->collisions_']
        sources = ['sim/simx/types.h', 'sim/simx/mem/memory.cpp']
        aggregation = 'single TxCrossBar cumulative component copied to returned statistics'
    elif name == 'tcu_lmem_reads':
        components = ['TcuTbuf::Impl::bufs_[0].reads_', 'TcuTbuf::Impl::bufs_[1].reads_']
        sources = ['sim/simx/tcu/tcu_tbuf.cpp', 'sim/simx/tcu/tcu_unit.cpp']
        aggregation = 'TcuTbuf::Impl::reads zero-initialized checked total over NUM_TCU_BLOCKS + 1 buffers'
    else:
        components = ['TcuUnit::Impl::perf_stats_.' + name.removeprefix('tcu_')]
        sources = ['sim/simx/tcu/tcu_unit.h', 'sim/simx/tcu/tcu_unit.cpp']
        aggregation = 'single cumulative component'
    selectors.append({'name':name,'mpm_class':cls,'csr':csr,'core_id':cid,'scope':scope,'unit':unit,
                      'class_macro':cls_macro,'csr_macro':csr_macro,'component_count':len(components),
                      'components':components,'source_paths':sources,'readout_path':'sim/simx/csr_unit.cpp',
                      'aggregation':aggregation,'initial_value':0,'launch_reset_preserves_components':True,
                      'monotonicity_condition':'bound production updaters only; no diagnostic assignment, decrement, reseed, replacement or reset of selected storage'})
assert len(selectors) == 33 and len(excluded) == 12
assert sum(s['component_count'] for s in selectors) == 40

def premise(id, statement, refs, runtime):
    return {'id':id,'statement':statement,'source_references':[{'path':p,'symbols':symbols} for p,symbols in refs],
            'runtime_obligation':runtime}

premises = [
    premise('P01', 'Exact route and inventory: RV64 serial timing, checked PERF, p02-tfr STD topology, 33 available core-zero selectors and 12 unavailable selectors.',
            [('tests/unittest/checked_counters/counter_access.cpp',['selectors','static_assert']),('ci/project/p06_contract.py',['_COUNTERS']),('sim/simx/socket.cpp',['Socket::Impl'])],
            'Retain generated configuration, compile flags, loaded executable/runtime/dependency identities, environment, capabilities and exact inventories for each real process; do not infer them from a profile name.'),
    premise('P02', 'All 40 selected backing components are zero at construction and undergo only nonnegative additions on the admitted production route.',
            [('sim/common/perf_counter.h',['PerfCounter::add','PerfCounter::nonnegative']),('sim/simx/core.h',['Core::PerfStats']),('sim/simx/processor_impl.h',['perf_mem_reads_','perf_mem_writes_','perf_mem_latency_']),('sim/simx/tcu/tcu_tbuf.cpp',['Buffer::reads_'])],
            'Use an unseeded new device lifetime; record all launch/reset generations and reject any checked failure. Type assignment/subtraction support alone does not establish monotonicity.'),
    premise('P03', 'Permitted launch reset preserves all selected cumulative backing storage; transient balances are reconciled before reset.',
            [('sim/simx/processor.cpp',['ProcessorImpl::reset','ProcessorImpl::launch_reset']),('sim/common/simobject.h',['SimPlatform::reset','SimPlatform::idle']),('sim/simx/core.cpp',['Core::Impl::reset']),('sim/simx/mem/cache.cpp',['CacheBank::on_reset']),('sim/simx/mem/local_mem.cpp',['LocalMem::Impl::reset']),('sim/simx/mem/mem_coalescer.cpp',['MemCoalescer::on_reset']),('sim/simx/types.h',['TxCrossBar::on_reset']),('sim/simx/tcu/tcu_unit.cpp',['TcuUnit::Impl::reset']),('sim/simx/tcu/tcu_tbuf.cpp',['Buffer::reset'])],
            'Before each direct-RAM launch reset, establish drained prior work, platform idle and zero pending reads; reset cannot rescue a failed or abandoned context.'),
    premise('P04', 'The final aggregate is evaluated with checked additions from zero before uint64 conversion; every component and every partial sum must fit.',
            [('sim/simx/mem/cache.h',['Cache::PerfStats::operator+=']),('sim/simx/mem/cache.cpp',['Cache::Impl::perf_stats']),('sim/simx/mem/cache_cluster.cpp',['CacheCluster::perf_stats']),('sim/simx/tcu/tcu_tbuf.cpp',['TcuTbuf::Impl::reads']),('sim/simx/csr_unit.cpp',['CsrUnit::get_csr'])],
            'Successfully query every one of the 33 exact selectors at the terminal boundary; a subset or per-component check alone is insufficient.'),
    premise('P05', 'Every operation queue has actually been destroyed and joined; no retained owner can submit later work.',
            [('sw/runtime/ai/runtime.cpp',['OperationState::release','RuntimeContext::release','ManagedMatmul::close']),('sw/runtime/common/queue.cpp',['Queue::~Queue']),('sw/runtime/common/vortex2_internal.h',['RefCounted::release','RefCounted::refs'])],
            'Retain operation/event completion statuses and actual queue destruction/join and final owner-reference observations. Public release success alone is insufficient.'),
    premise('P06', 'All launch, download and cache flush activity precedes the terminal readout; processor execution is collected and all queues are idle.',
            [('sim/simx/processor.cpp',['ProcessorImpl::run','ProcessorImpl::flush_caches']),('sw/runtime/common/async_run.h',['AsyncRun::collect','AsyncRun::invoke','AsyncRun::join']),('sw/runtime/simx/vortex.cpp',['vx_device::make_cp_hooks'])],
            'Establish successful execution, collected async run, zero pending reads, platform idle, CP completion and no residual DMA or flush before the terminal vector.'),
    premise('P07', 'Exclusive core-zero public low/high readout occurs while CP submission remains enabled; these MPM DCR reads do not tick the GPU model.',
            [('sw/runtime/common/perf.cpp',['vx_device_mpm_query']),('sw/runtime/common/device.cpp',['Device::cp_submit_dcr_read','Device::cp_quiesce_']),('sw/runtime/simx/vortex.cpp',['vx_device::cp_reg_read','vx_device::make_cp_hooks']),('sim/simx/core.cpp',['Core::Impl::dcr_read']),('sim/simx/csr_unit.cpp',['CsrUnit::get_csr'])],
            'Exclude concurrent submitters/batches and all-core unchecked host summation. Preserve raw status and both halves, full width reconstruction, no reset/tick during observation, and success before CP disable.'),
    premise('P08', 'After the last accepted read, destruction on the VM-off/direct-RAM route has no selected-counter updater or new GPU tick.',
            [('sw/runtime/common/device.cpp',['Device::~Device','Device::cp_quiesce_','Device::mem_free']),('sw/runtime/common/vortex2_internal.h',['CallbacksAdapter::~CallbacksAdapter']),('sw/runtime/common/callbacks.inc',['vx_dev_init: callbacks->dev_close']),('sw/runtime/simx/vortex.cpp',['vx_device::~vx_device','vx_device::host_mem_free','vx_device::make_cp_hooks']),('sim/simx/processor.cpp',['ProcessorImpl::~ProcessorImpl']),('sim/common/simobject.h',['SimPlatform::finalize','SimPlatform::cleanup'])],
            'Enter destruction only after P05-P07, with actual final reference. CP disable polling is not a replacement drain certificate; capture completion of the destructor path.'),
    premise('P09', 'The selected dependency finalizers and statistics emitters do not tick, send or deliver a GPU callback; the adapter does not drain at destruction.',
            [('sim/common/dram_sim.cpp',['RamulatorDram::~RamulatorDram','RamulatorDram::drain','RamulatorDram::tick','RamulatorDram::issue'])],
            'Bind the actual dependency binary to the selected source behavior; the companion source manifest alone and a cache hash do not establish compilation origin.'),
    premise('P10', 'A checked failure invalidates the process context and its numeric evidence; no reset, later query or fresh allocation rehabilitates that same lifetime.',
            [('sim/common/perf_counter.h',['PerfCounterError']),('sw/runtime/common/async_run.h',['AsyncRun::invoke','AsyncRun::require_healthy','AsyncRun::collect']),('sim/simx/core.cpp',['Core::Impl::dcr_read']),('sw/runtime/simx/vortex.cpp',['vx_device::cp_reg_read','vx_device::cp_reg_write'])],
            'Retain raw public failure/side-effect observations and independently fresh-context success. An interrupted MPM aggregate may leave mpm_class changed, so discard the failed context.'),
]

archive = SCRATCH / 'native/run-45026112992-attempt1.zip'
with zipfile.ZipFile(archive) as z:
    raw_report = z.read('checked-counters/report.json')
    report = json.loads(raw_report)
assert all(c['outcome']=='pass' for c in report['cells']) and len(report['cells'])==7
lifetime = {
    'schema_version':1,'contract':'simx-counter-terminal-source-argument-v1',
    'evidence_kind':'conditional-source-analysis','source_repository':'baabi-boo/AI-GPU',
    'source_revision':BOUND,'audited_base_revision':BASE,
    'production_sources_unchanged_from_base':True,
    'binding_scope':'Listed source premises, inventory helpers and caller ordering; not a complete transitive build closure or source-to-binary attestation.',
    'scope': {'xlen':64,'simulator':'SimX','timing':True,'performance_counters':True,'checked_counters_macro':'SIMX_CHECKED_COUNTERS=1',
              'profile':'p02-tfr','tensor_mode':'STD','clusters':1,'cores':1,'socket_size':1,'warps':4,'threads':4,'issue_width':1,
              'lsu_blocks':1,'tcu_blocks':1,'icache_enabled':True,'icache_banks':1,'dcache_enabled':True,'dcache_banks':2,
              'local_memory_enabled':True,'memory_channels':2,'virtual_memory':False,'l2':False,'l3':False,'wgmma':False,
              'cp_on_l2':0,'cp_on_l3':0,'cp_dma_route':'direct RAM / host memcpy; no LLC client','workers':1,'dram':'Ramulator HBM2',
              'mpm_core_id':0,'concurrent_submitters':False,'unavailable_selector_queries':False},
    'theorem': {'maximum':18446744073709551615,'selected_aggregates':33,'backing_components':40,
                'statement':'For one accepted unseeded lifetime, each selected component is nonnegative and monotone through admitted resets, and a successful final checked aggregate at T fits uint64. Thus for every earlier t each aggregate S_j(t) <= S_j(T) <= 2^64-1. No component or aggregate can have wrapped in that lifetime. A no-update suffix extends the bound until selected storage destruction.',
                'conditional_on':[p['id'] for p in premises],
                'not_established_by':['endpoint subtraction alone','component overflow checks without aggregate readout','seeded transport fixtures','a small unseeded scalar caller standing in for warm workspace','a cached dependency library hash standing in for build origin']},
    'selectors':selectors,'unavailable_selectors':excluded,'premises':premises,'files':files,
    'dependency_manifest':{'path':'docs/project/evidence/p06-counter-diagnostics/dependency-source-manifest.json','sha256':sha(dep_path.read_bytes())},
    'observed_native_evidence': {'kind':'seeded model diagnostic prerequisites','source_revision':BOUND,'github_run_id':45026112992,
        'url':'https://github.com/baabi-boo/AI-GPU/actions/runs/45026112992','artifact_id':14756780371,
        'original_archive_name':archive.name,'original_archive_sha256':sha(archive.read_bytes()),'original_archive_size_bytes':archive.stat().st_size,
        'report_member':'checked-counters/report.json','report_sha256':sha(raw_report),'passed_cells':[c['id'] for c in report['cells']],
        'ordinary_and_checked_each':{'checks':6389,'transport_half_reads':1788,'selectors':33,'components':40},
        'public_runtime':False,'warm_execution':False,'qualified':False},
    'public_diagnostic_checkpoint':{'source_revision':PUBLIC,'native_result':'not claimed by this source audit','relationship':'Separate new public-runtime diagnostics; requires its own retained native result and independent review.'},
    'remaining_obligations':[
        'Run and retain the real public-runtime diagnostics with raw failure statuses, suppressed processor and direct-RAM DMA side effects, terminal ordering, fresh-context controls and unchanged configuration.',
        'Bind a full unseeded warm-workspace caller and its reset/queue/refcount/CP/terminal/dependency behavior to this argument; the existing dynamic enabled-selector snapshot is insufficient.',
        'Qualify the precise later measurement binaries, generated configuration, loader dependencies, full caller, data and environment; no automatic inheritance from a diagnostic binary.',
        'Resolve dependency source-to-binary provenance or retain an explicit condition on actual loaded dependency behavior; never infer build origin from content hash alone.',
        'Complete required independent review and preserve failures/not-run evidence without weakening phase or acceptance gates.'
    ],
    'transient_and_unselected_exclusions':['ProcessorImpl::perf_mem_pending_reads_ (checked balance, decremented/reset, required zero before reset/terminal)',
        'SimPlatform clock and reset generation (control state; clock zeroing at cleanup is not counter preservation)',
        'Core::PerfStats::opds_stalls and cache bank-collision statistic outside the exact 33-selector inventory',
        'Dependency-internal statistics and nonselected GPU counters'],
    'absolute_no_wrap_bound':'not_established','qualified':False,'ready_for_warm':False,
    'acceptance_authority':False,'rtl_parity_claimed':False,'hardware_claimed':False,
    'phase_state':'P06/P06-T01 remain in_progress; P06-T01-A02/A03 remain open; warm-v1 remains blocked by P06-WARM-RV64-MPM-HIGH-HALF.',
}
manifest_path = save('lifetime-source-manifest.json', lifetime)
for path in (dep_path,manifest_path):
    print(path.relative_to(ROOT), sha(path.read_bytes()), path.stat().st_size)
