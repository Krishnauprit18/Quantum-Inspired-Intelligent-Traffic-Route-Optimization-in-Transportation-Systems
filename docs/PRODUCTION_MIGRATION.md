# Migrating this release into the existing Git repository

The Git repository on the developer workstation is the canonical history. Do **not** replace its `.git` directory and do not run `git init` again.

## Safe migration
From the parent directory of the existing Git-backed `quantroute` repository:

```bash
cd /path/to/existing/Quantum-Inspired\ Intelligent\ Traffic\ Route\ Optimization\ in\ Transportation\ Systems\ Using\ Metaheuristic\ Optimization/quantroute

git status
git switch -c production-foundation
```

Extract this release somewhere else, then copy its **contents** into the Git-backed directory while preserving `.git`:

```bash
rsync -av --delete \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='.env' \
  /path/to/extracted/quantroute-production-foundation/ ./
```

Then bootstrap and verify:

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
make verify
quantroute --help
```

Inspect the diff before committing:

```bash
git status
git diff --stat
git diff
```

Commit only after verification:

```bash
git add -A
git commit -m "feat: establish secure production foundation"
```

For hardened local deployment:

```bash
./scripts/secure_local_env.sh
docker compose up -d --build
curl http://127.0.0.1:8000/health
```

Protected endpoints require the API key stored in `.env`:

```bash
set -a; source .env; set +a
curl -H "X-API-Key: $QUANTROUTE_API_KEY" http://127.0.0.1:8000/v1/algorithms
```
