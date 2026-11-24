#!/usr/bin/env bash
set -euo pipefail
cd /tmp/ai-gpu-850acdff3419/repo
TMPDIR=/tmp/ai-gpu-850acdff3419/tmp PYTHONDONTWRITEBYTECODE=1 \
  /opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3.12 -B \
  /tmp/ai-gpu-850acdff3419/validation/A54/parser-parity.py \
  2>&1 | tee /tmp/ai-gpu-850acdff3419/validation/A54/parser-parity.log
/usr/bin/env -i \
  PATH=/tmp/ai-gpu-850acdff3419/validation/A37/environment/venv/bin:/usr/bin:/bin \
  HOME=/tmp/ai-gpu-850acdff3419/validation/A37/environment/home \
  TMPDIR=/tmp/ai-gpu-850acdff3419/validation/A37/environment/tmp \
  LANG=C LC_ALL=C TZ=UTC PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 \
  CCACHE_DISABLE=1 OBJCACHE= MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 THREADS=1 \
  /tmp/ai-gpu-850acdff3419/validation/A37/environment/venv/bin/python3 \
  /tmp/ai-gpu-850acdff3419/validation/A54/validate.py \
  2>&1 | tee /tmp/ai-gpu-850acdff3419/validation/A54/focused.log
