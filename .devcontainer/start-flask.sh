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

# Codespaces resets forwarded ports to Private on every restart. Once Flask is
# listening, flip 8587 back to Public (retrying while Codespaces registers the port),
# in the background so startup isn't blocked.
if [ -n "${CODESPACE_NAME:-}" ]; then
  # setsid + nohup: Codespaces kills leftover child processes when startup finishes.
  setsid nohup bash -c '
    for _ in $(seq 1 30); do
      curl -s -o /dev/null http://127.0.0.1:8587/api/id && break
      sleep 2
    done
    for _ in $(seq 1 10); do
      if gh codespace ports visibility 8587:public -c "$CODESPACE_NAME" >/dev/null 2>&1; then
        echo "Port 8587 set to Public."
        exit 0
      fi
      sleep 3
    done
    echo "Could not set port 8587 to Public automatically: set it in the Ports tab (or add a GH_TOKEN Codespaces secret with the codespace scope)."
  ' >> flask.log 2>&1 < /dev/null &
  echo "Shoreline backend: https://${CODESPACE_NAME}-8587.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}" | tee -a flask.log
fi
