#!/usr/bin/env bash
set -euo pipefail

# One-click publish/update for Azure Container Apps.
# - Cloud build in ACR (no local Docker arch issues)
# - Update Container App + Job to the new image
# - Optional: sync secrets/env vars from backend/.env

RG="${RG:-rg-zgen}"
APP_NAME="${APP_NAME:-marco}"
JOB_NAME="${JOB_NAME:-marco-ingest}"
SCHEDULE_JOB_NAME="${SCHEDULE_JOB_NAME:-marco-ingest-daily}"
# Default: 23:00 UTC daily (≈ morning Australia East; DST shifts by 1h).
SCHEDULE_CRON="${SCHEDULE_CRON:-0 23 * * *}"
ENABLE_SCHEDULE_JOB="${ENABLE_SCHEDULE_JOB:-1}"
ACR_NAME="${ACR_NAME:-regzen}"
IMAGE_REPO="${IMAGE_REPO:-marco}"

usage() {
  cat <<'USAGE'
Usage:
  ./deploy/publish.sh [TAG] [--no-config]
  ./deploy/publish.sh --no-config [TAG]

If TAG is omitted, defaults to YYYYMMDDHHMM (to minute).
USAGE
}

az_retry() {
  local attempt=1
  local max_attempts=3
  local sleep_s=2
  while true; do
    if "$@"; then
      return 0
    fi
    if (( attempt >= max_attempts )); then
      echo "ERROR: command failed after ${attempt} attempts: $*" >&2
      return 1
    fi
    echo "WARN: command failed (attempt ${attempt}/${max_attempts}), retrying in ${sleep_s}s: $*" >&2
    sleep "$sleep_s"
    attempt=$((attempt + 1))
    sleep_s=$((sleep_s * 2))
  done
}

TAG=""
SYNC_CONFIG=1

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 0
      ;;
    --no-config)
      SYNC_CONFIG=0
      ;;
    --*)
      echo "Unknown option: $arg" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -z "$TAG" ]]; then
        TAG="$arg"
      else
        echo "Unexpected argument: $arg" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
done

if [[ -z "$TAG" ]]; then
  TAG="$(date +%Y%m%d%H%M)"
fi

if [[ "$TAG" == -* ]]; then
  echo "Invalid TAG: $TAG" >&2
  usage >&2
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${SYNC_CONFIG:-1}" == "0" ]]; then
  SYNC_CONFIG=0
fi

echo "==> Building image in ACR: ${ACR_NAME}.azurecr.io/${IMAGE_REPO}:${TAG}"
az acr build --registry "$ACR_NAME" --image "${IMAGE_REPO}:${TAG}" .

IMAGE="${ACR_NAME}.azurecr.io/${IMAGE_REPO}:${TAG}"

ENV_ID="${ENV_ID:-}"
REGISTRY_SERVER="${REGISTRY_SERVER:-${ACR_NAME}.azurecr.io}"
REGISTRY_IDENTITY="${REGISTRY_IDENTITY:-}"

if [[ -z "$ENV_ID" ]]; then
  ENV_ID="$(az containerapp job show -g "$RG" -n "$JOB_NAME" --query properties.environmentId -o tsv 2>/dev/null || true)"
fi

if [[ -z "$REGISTRY_IDENTITY" ]]; then
  REGISTRY_IDENTITY="$(az containerapp job show -g "$RG" -n "$JOB_NAME" --query properties.configuration.registries[0].identity -o tsv 2>/dev/null || true)"
fi

if [[ "$ENABLE_SCHEDULE_JOB" == "1" ]]; then
  if ! az containerapp job show -g "$RG" -n "$SCHEDULE_JOB_NAME" >/dev/null 2>&1; then
    if [[ -z "$ENV_ID" ]]; then
      echo "ERROR: ENV_ID is required to create scheduled job (set ENV_ID or ensure $JOB_NAME exists)." >&2
      exit 2
    fi
    if [[ -z "$REGISTRY_IDENTITY" ]]; then
      echo "ERROR: REGISTRY_IDENTITY is required to create scheduled job (set REGISTRY_IDENTITY or ensure $JOB_NAME has registry configured)." >&2
      exit 2
    fi

    echo "==> Creating scheduled job: $SCHEDULE_JOB_NAME (cron: $SCHEDULE_CRON)"
    az_retry az containerapp job create \
      -g "$RG" \
      -n "$SCHEDULE_JOB_NAME" \
      --environment "$ENV_ID" \
      --image "$IMAGE" \
      --trigger-type Schedule \
      --cron-expression "$SCHEDULE_CRON" \
      --replica-timeout 7200 \
      --replica-retry-limit 1 \
      --command sh \
      --args /app/backend/run_ingest.sh \
      --registry-server "$REGISTRY_SERVER" \
      --registry-identity "$REGISTRY_IDENTITY" \
      >/dev/null
  fi
fi

if [[ $SYNC_CONFIG -eq 1 && -f backend/.env ]]; then
  echo "==> Syncing secrets/env vars from backend/.env (no values printed)"
  # shellcheck disable=SC1091
  set -a
  source backend/.env
  set +a

  # App secrets
  secrets=()
  if [[ -n "${PGPASSWORD:-}" ]]; then secrets+=("pgpassword=${PGPASSWORD}"); fi
  if [[ -n "${TELEMETRY_SALT:-}" ]]; then secrets+=("telemetrysalt=${TELEMETRY_SALT}"); fi
  if [[ -n "${AZURE_OPENAI_API_KEY:-}" ]]; then secrets+=("aoai-key=${AZURE_OPENAI_API_KEY}"); fi

  if [[ ${#secrets[@]} -gt 0 ]]; then
    az containerapp secret set -g "$RG" -n "$APP_NAME" --secrets "${secrets[@]}" >/dev/null
  fi

  # Job secrets (only what it needs)
  job_secrets=()
  if [[ -n "${PGPASSWORD:-}" ]]; then job_secrets+=("pgpassword=${PGPASSWORD}"); fi
  if [[ ${#job_secrets[@]} -gt 0 ]]; then
    az containerapp job secret set -g "$RG" -n "$JOB_NAME" --secrets "${job_secrets[@]}" >/dev/null
    if [[ "$ENABLE_SCHEDULE_JOB" == "1" ]]; then
      if az containerapp job show -g "$RG" -n "$SCHEDULE_JOB_NAME" >/dev/null 2>&1; then
        az_retry az containerapp job secret set -g "$RG" -n "$SCHEDULE_JOB_NAME" --secrets "${job_secrets[@]}" >/dev/null
      fi
    fi
  fi

  # App env vars
  app_env=()
  if [[ -n "${PGHOST:-}" ]]; then app_env+=("PGHOST=${PGHOST}"); fi
  if [[ -n "${PGUSER:-}" ]]; then app_env+=("PGUSER=${PGUSER}"); fi
  if [[ -n "${PGPORT:-}" ]]; then app_env+=("PGPORT=${PGPORT}"); fi
  if [[ -n "${PGDATABASE:-}" ]]; then app_env+=("PGDATABASE=${PGDATABASE}"); fi
  if [[ -n "${PGSSLMODE:-}" ]]; then app_env+=("PGSSLMODE=${PGSSLMODE}"); fi
  if [[ -n "${PGPASSWORD:-}" ]]; then app_env+=("PGPASSWORD=secretref:pgpassword"); fi

  if [[ -n "${TELEMETRY_ENABLED:-}" ]]; then app_env+=("TELEMETRY_ENABLED=${TELEMETRY_ENABLED}"); fi
  if [[ -n "${TELEMETRY_SALT:-}" ]]; then app_env+=("TELEMETRY_SALT=secretref:telemetrysalt"); fi

  if [[ -n "${AZURE_OPENAI_ENDPOINT:-}" ]]; then app_env+=("AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"); fi
  if [[ -n "${AZURE_OPENAI_API_KEY:-}" ]]; then app_env+=("AZURE_OPENAI_API_KEY=secretref:aoai-key"); fi
  if [[ -n "${AZURE_OPENAI_DEPLOYMENT:-}" ]]; then app_env+=("AZURE_OPENAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT}"); fi
  if [[ -n "${AZURE_OPENAI_API_VERSION:-}" ]]; then app_env+=("AZURE_OPENAI_API_VERSION=${AZURE_OPENAI_API_VERSION}"); fi

  if [[ ${#app_env[@]} -gt 0 ]]; then
    az containerapp update -g "$RG" -n "$APP_NAME" --set-env-vars "${app_env[@]}" >/dev/null
  fi

  # Job env vars
  job_env=()
  if [[ -n "${PGHOST:-}" ]]; then job_env+=("PGHOST=${PGHOST}"); fi
  if [[ -n "${PGUSER:-}" ]]; then job_env+=("PGUSER=${PGUSER}"); fi
  if [[ -n "${PGPORT:-}" ]]; then job_env+=("PGPORT=${PGPORT}"); fi
  if [[ -n "${PGDATABASE:-}" ]]; then job_env+=("PGDATABASE=${PGDATABASE}"); fi
  if [[ -n "${PGSSLMODE:-}" ]]; then job_env+=("PGSSLMODE=${PGSSLMODE}"); fi
  if [[ -n "${PGPASSWORD:-}" ]]; then job_env+=("PGPASSWORD=secretref:pgpassword"); fi

  if [[ ${#job_env[@]} -gt 0 ]]; then
    az containerapp job update -g "$RG" -n "$JOB_NAME" --set-env-vars "${job_env[@]}" >/dev/null
    if [[ "$ENABLE_SCHEDULE_JOB" == "1" ]]; then
      if az containerapp job show -g "$RG" -n "$SCHEDULE_JOB_NAME" >/dev/null 2>&1; then
        az_retry az containerapp job update -g "$RG" -n "$SCHEDULE_JOB_NAME" --set-env-vars "${job_env[@]}" >/dev/null
      fi
    fi
  fi
else
  echo "==> Skipping config sync (backend/.env missing or --no-config)"
fi

echo "==> Updating Container App + Job images"
az containerapp update -g "$RG" -n "$APP_NAME" --image "$IMAGE" >/dev/null
az containerapp job update -g "$RG" -n "$JOB_NAME" --image "$IMAGE" >/dev/null
if [[ "$ENABLE_SCHEDULE_JOB" == "1" ]]; then
  if az containerapp job show -g "$RG" -n "$SCHEDULE_JOB_NAME" >/dev/null 2>&1; then
    az_retry az containerapp job update -g "$RG" -n "$SCHEDULE_JOB_NAME" --image "$IMAGE" >/dev/null
  fi
fi

FQDN="$(az containerapp show -g "$RG" -n "$APP_NAME" --query properties.configuration.ingress.fqdn -o tsv)"

echo "==> Done"
echo "App URL: https://${FQDN}"
