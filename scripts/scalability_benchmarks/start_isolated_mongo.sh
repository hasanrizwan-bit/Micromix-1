#!/usr/bin/env bash
# Start a DISPOSABLE mongod used only by the scalability benchmarks.
#
# - Separate port (27099), never the default 27017 used by the developer DB.
# - Separate dbPath under scripts/scalability_benchmarks/.work/mongo-data
#   (git-ignored), so it can never touch /opt/homebrew/var/mongodb.
# - Bound to 127.0.0.1 only.
# - A marker document (bench_meta.ownership) is written by bench_common.py on
#   first connect; every benchmark refuses to run unless the marker is present
#   and matches, and refuses any port other than BENCH_MONGO_PORT.
#
# Usage: scripts/scalability_benchmarks/start_isolated_mongo.sh   (foreground)
#        Stop with Ctrl-C (or kill the PID). Delete .work/mongo-data to reset.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${BENCH_MONGO_PORT:-27099}"
DATA="$HERE/.work/mongo-data"
LOG="$HERE/.work/logs/mongod-bench.log"
if [ "$PORT" = "27017" ]; then
  echo "Refusing to use port 27017 (developer database)." >&2
  exit 2
fi
mkdir -p "$DATA" "$(dirname "$LOG")"
exec mongod --port "$PORT" --bind_ip 127.0.0.1 --dbpath "$DATA" \
  --wiredTigerCacheSizeGB 1 --logpath "$LOG" --logappend
