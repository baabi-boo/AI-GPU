set -eu
P05_SOURCE="$PWD"
P05_BUNDLE=/absolute/qualified/bundle
P05_OUT=/absolute/new/package-run
mkdir "$P05_OUT"
python3.12 -B - "$P05_SOURCE" "$P05_OUT/source" <<'PY'
from pathlib import Path
import runpy
import shutil
import sys
source, stage = map(Path, sys.argv[1:])
paths = runpy.run_path(str(source / "python/vortex_ai/_bundle.py"))["SOURCE_PATHS"]
stage.mkdir()
for name in (*paths, "LICENSE", "python/README.md"):
    target = stage / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / name, target)
PY
mkdir "$P05_OUT/sdist" "$P05_OUT/unpacked" "$P05_OUT/wheel"
(
  cd "$P05_OUT/source"
  VORTEX_AI_BUNDLE="$P05_BUNDLE" python3.12 -B -c \
    'import sys; from setuptools.build_meta import build_sdist; print(build_sdist(sys.argv[1]))' \
    "$P05_OUT/sdist"
)
tar -xzf "$P05_OUT/sdist/vortex_ai-0.1.0.tar.gz" -C "$P05_OUT/unpacked"
env -u VORTEX_AI_BUNDLE CC=gcc CXX=g++ python3.12 -m pip --isolated wheel \
  --no-index --no-deps --no-build-isolation --no-cache-dir \
  --wheel-dir "$P05_OUT/wheel" "$P05_OUT/unpacked/vortex_ai-0.1.0"
python3.12 -m venv --copies "$P05_OUT/venv"
"$P05_OUT/venv/bin/python" -I -m pip --isolated install \
  --no-index --no-deps --no-compile "$P05_OUT"/wheel/*.whl
"$P05_OUT/venv/bin/python" -I -c \
  'import vortex_ai; print(vortex_ai.__file__); print(vortex_ai.build_info())'
