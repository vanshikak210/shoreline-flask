#!/usr/bin/env bash
# Starts the Shoreline backend inside a Codespace so the github.io site can call it.
set -u
cd "$(dirname "$0")/.."

# Stable signing key per codespace, so logins survive restarts (not committed).
mkdir -p instance/volumes
[ -f instance/secret_key ] || python3 -c "import secrets;print(secrets.token_hex(32))" > instance/secret_key
export SECRET_KEY="$(cat instance/secret_key)"
# Cross-site cookie (github.io -> app.github.dev) needs Secure + SameSite=None.
export IS_PRODUCTION=true
export PASSWORD_HASH_ITERATIONS=200000
export DEFAULT_PASSWORD="${DEFAULT_PASSWORD:-$(python3 -c "import secrets;print(secrets.token_urlsafe(16))")}"

python3 scripts/render_init.py >> flask.log 2>&1

# Restart cleanly if it was already running.
pkill -f "gunicorn main:app" 2>/dev/null
nohup python3 -m gunicorn main:app --workers 1 --threads 4 --timeout 60 \
  --bind 0.0.0.0:8587 --access-logfile - >> flask.log 2>&1 &

# Codespaces resets forwarded ports to Private (on restart, sometimes on reconnect).
# Once Flask is listening, a background watchdog keeps 8587 Public.
if [ -n "${CODESPACE_NAME:-}" ]; then
  # Only one watchdog at a time if this script runs again.
  [ -f instance/port-watchdog.pid ] && kill "$(cat instance/port-watchdog.pid)" 2>/dev/null
  # setsid + nohup: Codespaces kills leftover child processes when startup finishes.
  setsid nohup bash -c '
    for _ in $(seq 1 30); do
      curl -s -o /dev/null http://127.0.0.1:8587/api/id && break
      sleep 2
    done
    # Watchdog: Codespaces can flip the port back to Private (restarts, reconnects),
    # so keep checking and set it Public again whenever it is not.
    warned=""
    while true; do
      vis=$(gh codespace ports -c "$CODESPACE_NAME" --json sourcePort,visibility \
            -q ".[] | select(.sourcePort==8587) | .visibility" 2>/dev/null)
      if [ "$vis" != "public" ]; then
        if gh codespace ports visibility 8587:public -c "$CODESPACE_NAME" >/dev/null 2>&1; then
          echo "$(date -u +%H:%M:%S) Port 8587 set to Public (was: ${vis:-unknown})."
        elif [ -z "$warned" ]; then
          echo "Could not set port 8587 to Public: add a GH_TOKEN Codespaces secret with the codespace scope, or set it in the Ports tab."
          warned=1
        fi
      fi
      sleep 30
    done
  ' >> flask.log 2>&1 < /dev/null &
  echo $! > instance/port-watchdog.pid
  echo "Shoreline backend: https://${CODESPACE_NAME}-8587.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}" | tee -a flask.log
fi
