#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-/home/user/n8n}"
cd "$ROOT"

NODE_DIR=/opt/node24
NODE_VERSION=v24.10.0
PGBIN=/usr/lib/postgresql/16/bin
PGDATA=/var/lib/postgresql/16/crm

say() { echo "[setup] $*"; }

if [ ! -x "$NODE_DIR/bin/node" ]; then
  say "installing Node $NODE_VERSION for eve"
  tmp=$(mktemp -d)
  curl -fsSL --max-time 300 -o "$tmp/node.tar.xz" \
    "https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-x64.tar.xz"
  mkdir -p "$NODE_DIR"
  tar -xJf "$tmp/node.tar.xz" -C "$NODE_DIR" --strip-components=1
  rm -rf "$tmp"
fi
export PATH="$NODE_DIR/bin:$PATH"
say "node $(node --version)"

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$NODE_DIR/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

if [ ! -f .env ]; then
  say "writing .env"
  cat > .env <<EOF
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/crm?schema=public"
TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/crm_test?schema=public"

BETTER_AUTH_SECRET="$(openssl rand -base64 32)"
ALLOWED_SIGN_IN="vertexholgroup@gmail.com"

GOOGLE_CLIENT_ID="ci-only-google-client-id"
GOOGLE_CLIENT_SECRET="ci-only-google-client-secret"

API_URL="http://localhost:3001"
APP_URL="http://localhost:3000"
AGENT_URL="http://127.0.0.1:2000"
AGENT_PORT="2000"

AGENT_BRIDGE_SECRET="$(openssl rand -base64 32)"

CRM_TELEMETRY_DISABLED="1"
EOF
fi

say "installing dependencies"
bun install

mkdir -p /var/run/postgresql /var/log/postgresql "$(dirname "$PGDATA")"
chown -R postgres:postgres /var/lib/postgresql /var/run/postgresql /var/log/postgresql

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  say "initialising postgres"
  pw=$(mktemp)
  echo postgres > "$pw"
  chown postgres "$pw"
  su postgres -c "$PGBIN/initdb -D $PGDATA -U postgres --auth-local=trust --auth-host=md5 --pwfile=$pw" >/dev/null
  rm -f "$pw"
fi

if ! su postgres -c "$PGBIN/pg_isready -h localhost -p 5432" >/dev/null 2>&1; then
  say "starting postgres"
  su postgres -c "$PGBIN/pg_ctl -D $PGDATA -l /var/log/postgresql/crm.log \
    -o '-c listen_addresses=localhost -p 5432' start -w -t 60" >/dev/null
fi

export PGPASSWORD=postgres
for name in crm crm_test; do
  if ! psql -h localhost -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$name'" | grep -q 1; then
    say "creating database $name"
    createdb -h localhost -U postgres "$name"
  fi
done

set -a
. ./.env
set +a

say "applying migrations"
bun run db:deploy >/dev/null
bun run db:test >/dev/null

if [ "$(psql -h localhost -U postgres -d crm -tAc 'SELECT count(*) FROM company')" = "0" ]; then
  say "seeding the demo pipeline"
  bun run db:seed >/dev/null
fi

psql -h localhost -U postgres -d crm_test -c 'TRUNCATE "agentTask" CASCADE;' >/dev/null

say "ready. Start the three processes with: ./scripts/dev-up.sh"
