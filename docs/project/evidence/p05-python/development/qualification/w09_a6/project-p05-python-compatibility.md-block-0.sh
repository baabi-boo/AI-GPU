set -eu
P05_SOURCE="$PWD"
P05_TOOLS=/absolute/provisioned/tools
P05_RUN=/absolute/new/p05-fp16
P05_FORMAT=fp16
mkdir "$P05_RUN"

python3.12 "$P05_SOURCE/ci/project/p04_execute.py" run \
  --source-dir "$P05_SOURCE" --tools-dir "$P05_TOOLS" \
  --work-dir "$P05_RUN/native-work" --output "$P05_RUN/native-output" \
  --backend simx --format "$P05_FORMAT" --iterations 2 --jobs 2 \
  --timeout-seconds 1800 --run-timeout-seconds 180

python3.12 "$P05_SOURCE/ci/project/p05_execute.py" run \
  --source-dir "$P05_SOURCE" --tools-dir "$P05_TOOLS" \
  --native-build "$P05_RUN/native-work/simx-$P05_FORMAT" \
  --native-output "$P05_RUN/native-output" \
  --work-dir "$P05_RUN/python-work" --output "$P05_RUN/python-output" \
  --format "$P05_FORMAT" --jobs 2 \
  --timeout-seconds 1800 --run-timeout-seconds 180
