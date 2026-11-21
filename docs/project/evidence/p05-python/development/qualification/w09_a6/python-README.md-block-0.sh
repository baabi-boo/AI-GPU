P05_VENV=/absolute/installed/venv
P05_BUNDLE=/absolute/qualified/bundle
"$P05_VENV/bin/python" -I -B -m vortex_ai.launch --bundle "$P05_BUNDLE" -- \
  /absolute/example.py "$P05_BUNDLE"
