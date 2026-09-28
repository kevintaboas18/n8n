#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

NODE_DIR=/opt/node24
PGBIN=/usr/lib/postgresql/16/bin
PGDATA=/var/lib/postgresql/16/crm
LOGS="${CRM_LOG_DIR:-/tmp/crm-logs}"

mkdir -p "$LOGS"
say() { echo "[dev-up] $*"; }

if [ -x "$NODE_DIR/bin/node" ]; then
  export PATH="$NODE_DIR/bin:$PATH"
fi

if ! su postgres -c "$PGBIN/pg_isready -h localhost -p 5432" >/dev/null 2>&1; then
  say "starting postgres"
  mkdir -p /var/run/postgresql
  chown postgres:postgres /var/run/postgresql
  su postgres -c "$PGBIN/pg_ctl -D $PGDATA -l /var/log/postgresql/crm.log \
    -o '-c listen_addresses=localhost -p 5432' start -w -t 60" >/dev/null
fi

up() { curl -sf -o /dev/null --max-time 5 "$1"; }

start() {
  local name=$1 dir=$2 probe=$3
  shift 3
  if up "$probe"; then
    say "$name already up"
    return
  fi
  say "starting $name"
  ( cd "$dir" && setsid nohup "$@" > "$LOGS/$name.log" 2>&1 < /dev/null & ) \
    >/dev/null 2>&1 </dev/null
}

start api    apps/api   http://localhost:3001/    bun src/main.ts
start app    apps/app   http://localhost:3000/    bunx next dev
start agent  apps/agent http://127.0.0.1:2000/    bun run dev:headless

say "waiting"
for _ in $(seq 1 60); do
  if up http://localhost:3001/ && up http://localhost:3000/ && up http://127.0.0.1:2000/; then
    say "app http://localhost:3000 · api http://localhost:3001 · agent http://127.0.0.1:2000"
    say "logs in $LOGS"
    exit 0
  fi
  sleep 5
done

say "not everything answered in time. Check $LOGS"
exit 1
