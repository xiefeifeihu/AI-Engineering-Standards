#!/usr/bin/env bash
set -euo pipefail

# AI Context Pack Export Script (Bash / WSL version)
# Exports clean, secret-free project context for AI review or session recovery.

PROJECT_DIR="${1:-}"
OUTPUT_DIR="${2:-}"

if [[ -z "$PROJECT_DIR" || ! -d "$PROJECT_DIR" ]]; then
    echo "Usage: $0 <project_directory> [output_directory]"
    exit 1
fi

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$(cd "$PROJECT_DIR/.." && pwd)/context-exports"
fi
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TEMP_STAGE="/tmp/ctx-stage-${PROJECT_NAME}-${TIMESTAMP}"
rm -rf "$TEMP_STAGE"
mkdir -p "$TEMP_STAGE"

cleanup() {
    rm -rf "$TEMP_STAGE"
}
trap cleanup EXIT

echo "[1/4] Capturing Git runtime state..."
cat <<EOF > "$TEMP_STAGE/GIT-STATE-SNAPSHOT.txt"
================================================================================
AI CONTEXT PACK - GIT RUNTIME SNAPSHOT
Timestamp: $(date +"%Y-%m-%d %H:%M:%S")
Project Path: $PROJECT_DIR
================================================================================

[Current Commit]
$(git -C "$PROJECT_DIR" rev-parse HEAD 2>&1 || echo "None")

[Current Branch]
$(git -C "$PROJECT_DIR" branch --show-current 2>&1 || echo "None")

[Remote Repositories]
$(git -C "$PROJECT_DIR" remote -v 2>&1 || echo "None")

[Working Tree Status]
$(git -C "$PROJECT_DIR" status --short 2>&1 || echo "Clean")

[Recent 5 Commits]
$(git -C "$PROJECT_DIR" log -n 5 --oneline 2>&1 || echo "None")
EOF

echo "[2/4] Copying project documentation and core files..."
# Root documentation
[[ -f "$PROJECT_DIR/README.md" ]] && cp "$PROJECT_DIR/README.md" "$TEMP_STAGE/"
[[ -f "$PROJECT_DIR/AGENTS.md" ]] && cp "$PROJECT_DIR/AGENTS.md" "$TEMP_STAGE/"

# Docs directory excluding archive and hidden/superseded
if [[ -d "$PROJECT_DIR/docs" ]]; then
    mkdir -p "$TEMP_STAGE/docs"
    find "$PROJECT_DIR/docs" -type f \
        ! -path "*/archive/*" \
        ! -name "*SUPERSEDED*" \
        ! -name ".*" \
        ! -name "desktop.ini" \
        -exec bash -c '
            for file; do
                rel="${file#'"$PROJECT_DIR"'/docs/}"
                target="'"$TEMP_STAGE"'/docs/$rel"
                mkdir -p "$(dirname "$target")"
                cp "$file" "$target"
            done
        ' bash {} +
fi

# Scripts directory (network gates only)
if [[ -d "$PROJECT_DIR/scripts" ]]; then
    mkdir -p "$TEMP_STAGE/scripts"
    find "$PROJECT_DIR/scripts" -type f -name "*gate*" \
        -exec bash -c '
            for file; do
                rel="${file#'"$PROJECT_DIR"'/scripts/}"
                target="'"$TEMP_STAGE"'/scripts/$rel"
                mkdir -p "$(dirname "$target")"
                cp "$file" "$target"
            done
        ' bash {} +
fi

echo "[3/4] Creating zip archive..."
COMMIT_SHORT="$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo "nocommit")"
ZIP_NAME="${PROJECT_NAME}-context-${TIMESTAMP}-${COMMIT_SHORT}.zip"
ZIP_PATH="${OUTPUT_DIR}/${ZIP_NAME}"

(cd "$TEMP_STAGE" && zip -r -q "$ZIP_PATH" .)

echo "[4/4] Verification & Cleanup..."
echo "Export completed successfully:"
echo "Output Archive: $ZIP_PATH"
ls -lh "$ZIP_PATH"
