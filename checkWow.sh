#!/usr/bin/env bash
set -euo pipefail

# ─── CONFIG ──────────────────────────────────────────────────────────
PROJECTS=(
  "/home/dkrant/projects/ambition/connectivity-wifi-eap/unit-tests"
#   "/home/dkrant/projects/ambition/connectivity-backend-monitor"
#   "/home/dkrant/projects/ambition/connectivity-configuration"
#   "/home/dkrant/projects/ambition/connectivity-statistics-collector"
#   "/home/dkrant/projects/ambition/connectivity-diagnostics"
)

STACK_DIR="/home/dkrant/projects/WoWAnnotator"
MODEL_TAG="qwen3:4b"

ISSUE_ID="CONAVANTG-0000"
BRANCH="$ISSUE_ID"
COMMIT_TITLE="Chore: Update UT comments & headers"
COMMIT_MSG=$'Updates UT comments and copyright headers\n\nIssue-ID: CONAVANTG-0000'

COPY_REGEX='^\s*\*\s+It is Developed and programmed by MBition GmbH – Copyright © [0-9]{4} Daimler AG'

LOG_TS() { date +'%Y-%m-%d %H:%M:%S'; }

update_headers() {
  local changed=0
  mapfile -t FILES < <(
    git ls-files -- '*.cpp' '*.cc' '*.cxx' '*.hpp' '*.h'
  )
  for f in "${FILES[@]}"; do
    local year
    year=$(git log -1 --date=format:%Y --format=%ad -- "$f" 2>/dev/null || true)
    [[ -z $year ]] && continue 
    if head -10 "$f" | grep -qE "$COPY_REGEX" &&
       ! head -10 "$f" | grep -q "© $year Daimler"; then
      sed -i -E "0,/$COPY_REGEX/s// * It is Developed and programmed by MBition GmbH – Copyright © $year Daimler AG/" "$f"
      ((changed++))
    fi
  done
  echo "$changed"
}

echo "[$(LOG_TS)] ⏳ (re)building container stack"
cd "$STACK_DIR"
docker compose up -d --build
docker compose exec -T ollama ollama pull "$MODEL_TAG"

for PROJ in "${PROJECTS[@]}"; do
  echo "[$(LOG_TS)] ▶ Processing $PROJ"
  [[ ! -d "$PROJ/.git" ]] && { echo "[$(LOG_TS)] skipped (no git)"; continue; }
  pushd "$PROJ" >/dev/null

  git fetch origin
  git checkout master
  git pull --ff-only
  git switch -C "$BRANCH"

  docker compose -f "$STACK_DIR/docker-compose.yml" run --rm \
    --volume "$PROJ":/workspace/project \
    annotator /workspace/project


  hdr_changed=$(update_headers)
  [[ $hdr_changed -gt 0 ]] && echo "[$(LOG_TS)]  updated $hdr_changed header(s)"

  if ! git diff --quiet; then
    echo "[$(LOG_TS)]    ✚ committing & pushing"
    git add -u
    git commit -m "$COMMIT_TITLE" -m "$COMMIT_MSG"
    git push origin HEAD:refs/heads/"$BRANCH" --force

    # glab mr create \
    #   --source "$BRANCH" --target master \
    #   --title  "$COMMIT_TITLE" \
    #   --description "$COMMIT_MSG" \
    #   --remove-source-branch --yes || true
  else
    echo "[$(LOG_TS)]    ✓ no changes"
  fi
  popd >/dev/null
done

docker compose down

echo "[$(LOG_TS)] ✅ All projects processed"