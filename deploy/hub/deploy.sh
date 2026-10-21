#!/usr/bin/env bash
# Deploy ResearchOS Hub to Yandex Cloud Serverless Container + API Gateway.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HUB="$ROOT/hub"
DEPLOY="$ROOT/deploy/hub"

FOLDER_ID="${YC_FOLDER_ID:-b1gd4tuo1s1lu2b87fmf}"
CONTAINER_NAME="${HUB_CONTAINER_NAME:-researchos-hub}"
REGISTRY_NAME="${HUB_REGISTRY_NAME:-researchos-hub-cr}"
GATEWAY_NAME="${HUB_GATEWAY_NAME:-researchos-hub-gw}"
BUCKET_NAME="${HUB_S3_BUCKET:-researchos-hub-data}"
IMAGE_TAG="${HUB_IMAGE_TAG:-latest}"

if [[ -f "$HUB/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$HUB/.env"
  set +a
fi

: "${GITHUB_CLIENT_ID:?Set GITHUB_CLIENT_ID in hub/.env}"
: "${GITHUB_CLIENT_SECRET:?Set GITHUB_CLIENT_SECRET in hub/.env}"
: "${HUB_SESSION_SECRET:?Set HUB_SESSION_SECRET in hub/.env}"

echo "==> Ensure container registry"
REGISTRY_ID=""
if REGISTRY_JSON="$(yc container registry get --name "$REGISTRY_NAME" --folder-id "$FOLDER_ID" --format json 2>/dev/null)"; then
  REGISTRY_ID="$(echo "$REGISTRY_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi
if [[ -z "$REGISTRY_ID" ]]; then
  yc container registry create --name "$REGISTRY_NAME" --folder-id "$FOLDER_ID"
  REGISTRY_ID="$(yc container registry get --name "$REGISTRY_NAME" --folder-id "$FOLDER_ID" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi
REGISTRY_URI="cr.yandex/${REGISTRY_ID}/${CONTAINER_NAME}:${IMAGE_TAG}"

echo "==> Build & push image ${REGISTRY_URI} (linux/amd64)"
cd "$ROOT"
# YC Serverless Containers need amd64; Mac arm64 builds fail revision deploy with Internal error.
docker build --platform linux/amd64 -f hub/Dockerfile -t "$REGISTRY_URI" .
yc container registry configure-docker
docker push "$REGISTRY_URI"

echo "==> Ensure Object Storage bucket"
if ! yc storage bucket get --name "$BUCKET_NAME" >/dev/null 2>&1; then
  yc storage bucket create --name "$BUCKET_NAME" --folder-id "$FOLDER_ID"
fi

echo "==> Ensure serverless container"
CONTAINER_ID=""
if CONTAINER_JSON="$(yc serverless container get --name "$CONTAINER_NAME" --folder-id "$FOLDER_ID" --format json 2>/dev/null)"; then
  CONTAINER_ID="$(echo "$CONTAINER_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi
if [[ -z "$CONTAINER_ID" ]]; then
  yc serverless container create --name "$CONTAINER_NAME" --folder-id "$FOLDER_ID"
  CONTAINER_ID="$(yc serverless container get --name "$CONTAINER_NAME" --folder-id "$FOLDER_ID" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi

SA_NAME="${HUB_SA_NAME:-researchos-hub-sa}"
SA_ID=""
if SA_JSON="$(yc iam service-account get --name "$SA_NAME" --folder-id "$FOLDER_ID" --format json 2>/dev/null)"; then
  SA_ID="$(echo "$SA_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi
if [[ -z "$SA_ID" ]]; then
  yc iam service-account create --name "$SA_NAME" --folder-id "$FOLDER_ID"
  SA_ID="$(yc iam service-account get --name "$SA_NAME" --folder-id "$FOLDER_ID" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
fi

# Static keys for bucket access from container env (MVP).
if [[ -z "${HUB_S3_ACCESS_KEY:-}" || -z "${HUB_S3_SECRET_KEY:-}" ]]; then
  KEY_JSON="$(yc iam access-key create --service-account-id "$SA_ID" --format json)"
  export HUB_S3_ACCESS_KEY="$(echo "$KEY_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_key"]["key_id"])')"
  export HUB_S3_SECRET_KEY="$(echo "$KEY_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["secret"])')"
  echo "Created S3 access key for ${SA_NAME}. Save HUB_S3_ACCESS_KEY/HUB_S3_SECRET_KEY in hub/.env"
fi

yc serverless container revision deploy \
  --container-id "$CONTAINER_ID" \
  --image "$REGISTRY_URI" \
  --cores 1 \
  --memory 512MB \
  --execution-timeout 600s \
  --service-account-id "$SA_ID" \
  --environment "GITHUB_CLIENT_ID=${GITHUB_CLIENT_ID}" \
  --environment "GITHUB_CLIENT_SECRET=${GITHUB_CLIENT_SECRET}" \
  --environment "HUB_SESSION_SECRET=${HUB_SESSION_SECRET}" \
  --environment "HUB_PUBLIC_URL=${HUB_PUBLIC_URL:-}" \
  --environment "HUB_S3_BUCKET=${BUCKET_NAME}" \
  --environment "HUB_S3_ENDPOINT=https://storage.yandexcloud.net" \
  --environment "HUB_S3_ACCESS_KEY=${HUB_S3_ACCESS_KEY}" \
  --environment "HUB_S3_SECRET_KEY=${HUB_S3_SECRET_KEY}"

CONTAINER_URL="$(yc serverless container get --name "$CONTAINER_NAME" --folder-id "$FOLDER_ID" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"])')"

export HUB_PUBLIC_URL="${HUB_PUBLIC_URL:-}"
if [[ -z "$HUB_PUBLIC_URL" ]]; then
  echo "Container URL: $CONTAINER_URL"
  echo "Will create API Gateway; set HUB_PUBLIC_URL to gateway URL after deploy and update GitHub OAuth callback."
fi

python3 - "$DEPLOY/api-gateway.yaml" "$CONTAINER_ID" "$SA_ID" <<'PY'
import sys
from pathlib import Path
spec = Path(sys.argv[1]).read_text()
spec = spec.replace("__CONTAINER_ID__", sys.argv[2])
spec = spec.replace("__SERVICE_ACCOUNT_ID__", sys.argv[3])
Path(sys.argv[1] + ".rendered").write_text(spec)
PY

yc serverless api-gateway create --name "$GATEWAY_NAME" --folder-id "$FOLDER_ID" --spec "$DEPLOY/api-gateway.yaml.rendered" 2>/dev/null || \
  yc serverless api-gateway update --name "$GATEWAY_NAME" --folder-id "$FOLDER_ID" --spec "$DEPLOY/api-gateway.yaml.rendered"

GW_DOMAIN="$(yc serverless api-gateway get --name "$GATEWAY_NAME" --folder-id "$FOLDER_ID" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["domain"])')"
echo
echo "Deployed."
echo "API Gateway: https://${GW_DOMAIN}"
echo "Update GitHub OAuth callback: https://${GW_DOMAIN}/auth/callback"
echo "Set HUB_PUBLIC_URL=https://${GW_DOMAIN} and redeploy container revision if needed."
