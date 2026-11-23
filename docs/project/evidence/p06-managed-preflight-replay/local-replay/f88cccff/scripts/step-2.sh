set -euo pipefail
python3 ci/project/p06_managed_preflight_replay.py \
  --archive "$PWD/docs/project/evidence/p06-managed-preflight/native/run-45085300171-attempt1.zip" \
  --sha256 cee5be4dba875494f6eafb83484933ab7693428e4773b932a26d5b91bd17969d \
  --source-revision 57248e73dfce4ae2d21d2cbdb82c3953eef2e3db \
  --source-inventory "$PWD/docs/project/evidence/p06-managed-preflight/native/source-inventory-57248e73.json" \
  --source-inventory-sha256 72ca7e9237060ca2831a275811d27ec6fdb3507dfd9a00b693aa177aa68382e8 \
  --source-derivation "$PWD/docs/project/evidence/p06-managed-preflight/native/source-derivation-57248e73.json" \
  --source-derivation-sha256 3b25d30eceeee2dc5cebd1cce8ed7ab90da0fec64857e82fc7cc7fc3ca38e171 \
  --output "$P06_MANAGED_REPLAY_ROOT/evidence/replay.json" \
  2>&1 | tee "$P06_MANAGED_REPLAY_ROOT/evidence/replay.log"
