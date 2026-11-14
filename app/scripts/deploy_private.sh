#!/usr/bin/env bash
# Install this checkout as a private, key-free Agent Dairy demo on Linux.
set -euo pipefail
umask 077
cd -- "$(dirname -- "$0")/.."
app_dir=$PWD
host=${1:?Usage: bash scripts/deploy_private.sh PRIVATE_BIND_IP}
if [[ ! "$host" =~ ^[0-9.]+$ || "$host" == "0.0.0.0" ]]; then
  printf 'Enter one private IPv4 address for binding.\n' >&2
  exit 2
fi
export REQUIRE_PORTAL_LOGIN=1 OFFLINE_DEMO=1
export CATALOG_DB_PATH=data/synthetic.db
export DB_PATH=data/hosted-gateway.db
export SIGNING_KEY_PATH=data/hosted-signing.pem
export VALIO_API_KEY= ANTHROPIC_API_KEY= GEMINI_API_KEY=
export MCP_ALLOWED_ORIGINS="http://$host:8000"
if [[ "$app_dir" == *'"'* || "$app_dir" == *%* || "$app_dir" == *$'\n'* || "$app_dir" == *$'\r'* || "$app_dir" == *'\'* ]]; then
  printf 'Unsupported character in the deployment directory.\n' >&2
  exit 2
fi
if ! command -v uv >/dev/null; then
  printf 'Install uv first and make it available on PATH.\n' >&2
  exit 1
fi
uv sync --locked --no-dev
python="$app_dir/.venv/bin/python"
if [[ ! -f "$CATALOG_DB_PATH" ]]; then
  "$python" -m gateway.demo_catalog
fi

if systemctl --user show-environment >/dev/null 2>&1 &&
   [[ "$(loginctl show-user "$(id -u)" -p Linger --value 2>/dev/null)" == yes ]]; then
  unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p -- "$unit_dir"
  units=()
  write_unit() {
    local name=$1 module=$2 bind=$3 port=$4 prefix=$5
    units+=("agent-dairy-$name.service")
    cat > "$unit_dir/agent-dairy-$name.service" <<UNIT
[Unit]
Description=Agent Dairy $name
After=network-online.target
[Service]
WorkingDirectory=$app_dir
Environment=REQUIRE_PORTAL_LOGIN=1 OFFLINE_DEMO=1
Environment=CATALOG_DB_PATH=data/synthetic.db DB_PATH=data/hosted-gateway.db SIGNING_KEY_PATH=data/hosted-signing.pem
Environment=VALIO_API_KEY= ANTHROPIC_API_KEY= GEMINI_API_KEY=
Environment=MCP_ALLOWED_ORIGINS=http://$host:8000
ExecStart="$python" -m uvicorn $module:app --host $bind --port $port $prefix
Restart=on-failure
UMask=0077
[Install]
WantedBy=default.target
UNIT
  }
  write_unit client gateway.api "$host" 8000 ""
  if [[ ${FUNNEL_PORTALS:-0} == 1 ]]; then
    write_unit client-funnel gateway.api 127.0.0.1 18200 "--root-path /agent-dairy"
  fi
  systemctl --user daemon-reload
  systemctl --user enable "${units[@]}"
  systemctl --user restart "${units[@]}"
else
  printf 'Persistent user services require an enabled systemd user manager and lingering.\n' >&2
  printf 'To run the shared portal in this SSH session, use: %s\n' "$python scripts/run_local.py --host $host" >&2
  exit 1
fi
printf 'Workspace: http://%s:8000/\nAdmin panel: http://%s:8000/admin/\n' "$host" "$host"
