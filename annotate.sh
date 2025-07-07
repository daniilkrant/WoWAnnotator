#!/usr/bin/env bash
set -euo pipefail

# ─── CONFIG ──────────────────────────────────────────────────────────
PROJECTS=(
  "/home/dkrant/projects/ambition/connectivity-wifi-eap"
  "/home/dkrant/projects/ambition/connectivity-backend-monitor"
  "/home/dkrant/projects/ambition/connectivity-configuration"
  "/home/dkrant/projects/ambition/connectivity-statistics-collector"
  "/home/dkrant/projects/ambition/connectivity-diagnostics"
)

STACK_DIR="/home/dkrant/ai_for_aspice"          # docker-compose.yml lives here
MODEL_TAG="qwen3:4b"

ISSUE_ID="CONAVANTG-0000"
BRANCH="$ISSUE_ID"
COMMIT_TITLE="Chore: Update UT comments"
COMMIT_MSG=$'Updates UT commnts\n\nIssue-ID: CONAVANTG-0000'

LOG_TS() { date +'%Y-%m-%d %H:%M:%S'; }

# ─── PREPARE STACK ───────────────────────────────────────────────────
echo "[$(LOG_TS)] ⏳ (re)building container stack"
cd "$STACK_DIR"
docker compose up -d --build
docker compose exec -T ollama ollama pull "$MODEL_TAG"

# ─── PER-PROJECT LOOP ────────────────────────────────────────────────
for PROJ in "${PROJECTS[@]}"; do
  echo "[$(LOG_TS)] ▶ Processing $PROJ"
  if [[ ! -d "$PROJ/.git" ]]; then
    echo "[$(LOG_TS)]    ⚠ Skipped – not a git repo"; continue
  fi

  pushd "$PROJ" >/dev/null

  # 1) sync master
  git fetch origin
  git checkout master
  git pull --ff-only

  # 2) (re)create working branch
  git switch -C "$BRANCH"

  # 3) run annotator (bind-mount this repo root)
  docker compose run --rm \
    --volume "$PROJ":/workspace/project \
    annotator /workspace/project

  # 4) commit if anything changed
  if ! git diff --quiet; then
    echo "[$(LOG_TS)]    ✚ committing & pushing changes"
    git add -u
    git commit -m "$COMMIT_TITLE" -m "$COMMIT_MSG"
    git push origin HEAD:refs/heads/"$BRANCH" --force

    # 5) raise / update MR (glab auto-reuses if one already exists)
    glab mr create               \
      --source "$BRANCH"         \
      --target master            \
      --title  "$COMMIT_TITLE"   \
      --description "$COMMIT_MSG"\
      --remove-source-branch     \
      --yes || true
  else
    echo "[$(LOG_TS)]    ✓ no changes – nothing to commit"
  fi

  popd >/dev/null
done

echo "[$(LOG_TS)] ✅ All projects processed"
