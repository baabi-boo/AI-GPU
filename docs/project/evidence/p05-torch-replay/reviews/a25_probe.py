"""Independent host-only review probe; all archive bytes stay in memory."""
import ast
import gzip
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))
import p05_replay_installation as installation
from p06_replay import _archive_api

PATHS = ("ci/project/p05_replay_installation.py",
         "ci/project/test_p05_replay_nested_archives.py",
         "ci/project/p05_torch_replay.py",
         "docs/project/evidence/p05-torch/reviews/archive_reader.py")
before = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PATHS}

regular = tarfile.TarInfo("vortex_ai-0.1.0/setup.py")
regular.size = 8
control_tar = regular.tobuf(format=tarfile.GNU_FORMAT) + b"control\n" + bytes(504)
control = gzip.compress(control_tar + bytes(1024), mtime=0)
assert installation._sdist_members(control, _archive_api()) == {"setup.py": b"control\n"}
print("valid control accepted; compressed bytes:", len(control))

sparse = tarfile.TarInfo("vortex_ai-0.1.0/sparse.txt")
sparse.type = tarfile.GNUTYPE_SPARSE
header = bytearray(sparse.tobuf(format=tarfile.GNU_FORMAT))
header[482] = 1
header[148:156] = b"        "
header[148:156] = ("%06o\0 " % sum(header)).encode("ascii")
extension = bytearray(512)
extension[504] = 1
# One complete extension requests another; the next has 504 bytes, no flag.
for later in (False, True):
    payload = (control_tar if later else b"") + header + extension + bytes(504)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            list(archive)
    except IndexError:
        pass
    else:
        raise AssertionError("raw tar parser did not reproduce IndexError")
    compressed = gzip.compress(payload, mtime=0)
    try:
        installation._sdist_members(compressed, _archive_api())
    except installation.InstallationError as error:
        assert str(error) == "malformed source archive header"
        assert isinstance(error.__cause__, IndexError)
    else:
        raise AssertionError("malformed archive accepted")
    print("second-extension truncation normalized; later:", later,
          "compressed bytes:", len(compressed))

sentinel = IndexError("independent member-size validation sentinel")
require = installation._require
def checked_require(condition, message):
    if message == "source archive member is oversized":
        raise sentinel
    return require(condition, message)
with patch.object(installation, "_require", side_effect=checked_require):
    try:
        installation._sdist_members(control, _archive_api())
    except IndexError as error:
        assert error is sentinel
    else:
        raise AssertionError("unrelated validation IndexError was hidden")
print("validation-body IndexError escaped unchanged")

path = PATHS[0]
baseline = subprocess.check_output(
    ["git", "show", "d8abc24d2fd5dab5ceddbae3627e3d3eb9750358:" + path], cwd=ROOT, text=True)
def function(text):
    return next(n for n in ast.parse(text).body
                if isinstance(n, ast.FunctionDef) and n.name == "_sdist_members")
old, new = function(baseline), function((ROOT / path).read_text())
old_loop = next(n for n in ast.walk(old) if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple))
new_loop = next(n for n in ast.walk(new) if isinstance(n, ast.While))
body = new_loop.body[1:]
assert isinstance(body[1], ast.AugAssign) and body[1].target.id == "index"
body = body[:1] + body[2:]
assert ast.dump(ast.Module(body=old_loop.body, type_ignores=[])) == ast.dump(ast.Module(body=body, type_ignores=[]))
assert [ast.dump(n) for n in old.body[:3]] == [ast.dump(n) for n in new.body[:3]]
assert [ast.dump(n) for n in old.body[-2:]] == [ast.dump(n) for n in new.body[-2:]]
tries = [n for n in ast.walk(new) if isinstance(n, ast.Try)]
assert len(tries) == 2
assert [ast.unparse(n.body[0]) for n in tries] == [
    "archive = tarfile.open(fileobj=io.BytesIO(unpacked), mode='r:')", "item = next(entries)"]
assert all(len(n.body) == 1 for n in tries)
print("AST: validation body, pre/post-loop gates unchanged; catches surround only open/next")
assert before == {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in PATHS}
for path, digest in before.items():
    print(digest, path)
