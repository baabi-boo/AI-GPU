from pathlib import Path
import hashlib, json, os, re, subprocess, sys
from datetime import datetime, timezone
root=Path("/workspace/AI-GPU")
sys.path.insert(0,str(root/"ci/project"))
from baseline_process import run_bounded
out=root/"docs/project/evidence/p06-dependency-provenance/validation"
def profile():
 return [{"path":p.relative_to(root).as_posix(),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"size_bytes":p.stat().st_size} for p in sorted((root/"ci/project").glob("*.py"))]
modules=["test_p06_dependency_record","test_p06_dependency_receipt","test_p06_dependency_binary","test_p06_dependency_build","test_p06_dependency_graph","test_p06_dependency_repeated_inputs","test_p06_dependency_map_limits","test_p06_dependency_spdlog_selection"]
env=dict(os.environ,PATH="/workspace/p06-build-tools/cmake/data/bin:"+os.environ["PATH"],PYTHONPATH=str(root/"ci/project"),PYTHONDONTWRITEBYTECODE="1",OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1")
argv=[sys.executable,"-B","-m","unittest","-v",*modules]
before=profile(); started=datetime.now(timezone.utc).isoformat()
log=out/"w10_a06-spdlog-tests-01.log"
bounds=dict(timeout_seconds=120,min_free_bytes=15*1024**3,max_log_bytes=16*1024**2,max_rss_bytes=1024**3)
result=run_bounded(argv,root,env,log,resource_paths=(root,),**bounds)
after=profile();body=log.read_text()
document={"schema_version":1,"scope":"Independent archive-selection correction review; host fixture and explicitly scoped inert entry tests, not a complete pinned original","started_at_utc":started,"finished_at_utc":datetime.now(timezone.utc).isoformat(),"head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip(),"argv":argv,"cwd":str(root),"python_version":sys.version,"bounds":bounds,"supervision":result,"unit_summary":[x for x in body.splitlines() if re.match(r"^(Ran [0-9]+ tests|OK|FAILED)",x)],"source_before":before,"source_after":after,"source_unchanged":before==after,"qualification_or_acceptance_claimed":False}
path=out/"w10_a06-spdlog-tests-01.json";path.write_text(json.dumps(document,indent=2)+"\n")
print(json.dumps({k:document[k] for k in ("unit_summary","supervision","source_unchanged")}))
if result["outcome"]!="pass" or before!=after:raise SystemExit(1)
