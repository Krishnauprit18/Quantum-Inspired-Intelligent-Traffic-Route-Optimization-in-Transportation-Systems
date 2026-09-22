#!/usr/bin/env bash
set -euo pipefail
if [[ -e .env ]]; then
  echo '.env already exists; refusing to overwrite.' >&2
  exit 1
fi
KEY="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
cat > .env <<EOF
QUANTROUTE_ENV=production
QUANTROUTE_AUTH_ENABLED=true
QUANTROUTE_API_KEY=${KEY}
QUANTROUTE_ALLOWED_HOSTS=localhost,127.0.0.1
QUANTROUTE_DOCS_ENABLED=false
EOF
chmod 600 .env
echo 'Created .env with mode 600. Keep it out of Git.'
