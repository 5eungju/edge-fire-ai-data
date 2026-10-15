#!/usr/bin/env bash
set -euo pipefail

DATASET_KEY="71330"
FILE_KEY="${1:-485847}"  # default: VL.zip, 160.40 MB; label-only, not for model training
DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/raw"
mkdir -p "$DEST"
cd "$DEST"

if [[ -z "${AIHUB_API_KEY:-}" ]]; then
  read -rsp "AI Hub API key (input hidden): " AIHUB_API_KEY
  echo
  export AIHUB_API_KEY
fi

if [[ ! -x ./aihubshell ]]; then
  curl -fL "https://api.aihub.or.kr/api/aihubshell.do" -o ./aihubshell
  chmod +x ./aihubshell
fi

echo "Dataset ${DATASET_KEY}, file ${FILE_KEY} -> ${DEST}"
echo "AI Hub may require prior dataset approval. Files stay in data/raw (git-ignored)."
./aihubshell -mode d -datasetkey "$DATASET_KEY" -filekey "$FILE_KEY" -aihubapikey "$AIHUB_API_KEY"
