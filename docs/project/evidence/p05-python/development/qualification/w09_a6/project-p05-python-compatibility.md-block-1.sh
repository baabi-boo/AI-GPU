VENV=/absolute/fresh/venv
BUNDLE=/absolute/qualified/bundle
SCRIPT=/absolute/installed-check/p05_installed_check.py
REQUEST=/absolute/installed-check/request.json
OBSERVATIONS=/absolute/installed-check/observations.json
"$VENV/bin/python" -I -B -m vortex_ai.launch --bundle "$BUNDLE" -- \
  "$SCRIPT" --request "$REQUEST" --output "$OBSERVATIONS"
