# Azure Container Apps 部署（单镜像：前端+后端）

目标：把本仓库构建成一个镜像，在 Azure Container Apps (ACA) 里对外暴露 8000 端口：

- UI: `/`
- API: `/api/*`

已知信息：

- Managed Environment: `/subscriptions/96e7862a-aec2-4c4c-aec1-8c7223574a17/resourceGroups/rg-zgen/providers/Microsoft.App/managedEnvironments/zgen-env`
- ACR: `regzen`（login server 一般是 `regzen.azurecr.io`）

## 0) 变量

```bash
export SUBSCRIPTION_ID=96e7862a-aec2-4c4c-aec1-8c7223574a17
export RG=rg-zgen
export ENV_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG/providers/Microsoft.App/managedEnvironments/zgen-env"
export ACR_NAME=regzen
export ACR_SERVER="$ACR_NAME.azurecr.io"

# 你可以改名（如果已经存在同名 Container App 会走 update 流程）
export APP_NAME=marco

# 镜像 tag：用 git sha 或时间戳都行
export IMAGE_TAG=$(git rev-parse --short HEAD)
export IMAGE="$ACR_SERVER/$APP_NAME:$IMAGE_TAG"
```

## 0.5) 一键发布/更新（推荐）

仓库提供脚本 [deploy/publish.sh](deploy/publish.sh)：

```bash
chmod +x deploy/publish.sh

# 默认：用 ACR cloud build 构建镜像并更新 App/Job；同时从 backend/.env 同步 secrets/env（不打印敏感值）
./deploy/publish.sh

# 指定 tag
./deploy/publish.sh mytag

# 只构建+更新镜像，不同步 backend/.env（适合 CI）
./deploy/publish.sh --no-config

# 也可以同时指定 tag
./deploy/publish.sh mytag --no-config

# 只更新 ingest job（手动 job + 定时 job），不动 Web App（适合你只改了 ingest/采集逻辑）
./deploy/publish.sh --only-job --no-config

# 也支持指定 tag / 禁用 config 同步
./deploy/publish.sh --only-job mytag
./deploy/publish.sh --only-job --no-config mytag

# 可用环境变量覆盖默认值
# RG=rg-zgen APP_NAME=marco JOB_NAME=marco-ingest ACR_NAME=regzen IMAGE_REPO=marco ./deploy/publish.sh
```

## 1) 登录与选择订阅

```bash
az login
az account set --subscription "$SUBSCRIPTION_ID"
```

## 2) 构建并推送镜像到 ACR

优先推荐 ACR Cloud Build（不依赖本机 Docker 环境）：

```bash
az acr build -r "$ACR_NAME" -t "$APP_NAME:$IMAGE_TAG" .
```

如果你更想本机 build/push：

```bash
az acr login -n "$ACR_NAME"
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

## 3) 创建/更新 Container App

创建（第一次）：

```bash
az containerapp create \
  -n "$APP_NAME" \
  -g "$RG" \
  --environment "$ENV_ID" \
  --image "$IMAGE" \
  --ingress external \
  --target-port 8000 \
  --registry-server "$ACR_SERVER" \
  --registry-identity system
```

如果已存在则更新镜像：

```bash
az containerapp update -n "$APP_NAME" -g "$RG" --image "$IMAGE"
```

给系统分配的 Managed Identity 授权拉取 ACR（只需做一次）：

```bash
PRINCIPAL_ID=$(az containerapp identity show -n "$APP_NAME" -g "$RG" --query principalId -o tsv)
ACR_ID=$(az acr show -n "$ACR_NAME" --query id -o tsv)

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope "$ACR_ID"
```

## 4) 配置环境变量（连接 Azure Postgres 等）

推荐把敏感值放进 ACA secrets：

```bash
az containerapp secret set -n "$APP_NAME" -g "$RG" --secrets \
  pgpassword='REPLACE_ME' \
  telemetrysalt='REPLACE_ME'
```

然后设置环境变量（这里用 PG* 变量，让后端自动拼 `DATABASE_URL`）：

```bash
az containerapp update -n "$APP_NAME" -g "$RG" --set-env-vars \
  PGHOST=zgendb.postgres.database.azure.com \
  PGUSER=myadmin \
  PGPORT=5432 \
  PGDATABASE=postgres \
  PGSSLMODE=require \
  PGPASSWORD=secretref:pgpassword \
  TELEMETRY_ENABLED=true \
  TELEMETRY_SALT=secretref:telemetrysalt
```

可选：如果要启用 Azure OpenAI（同样建议走 secrets）：

```bash
az containerapp secret set -n "$APP_NAME" -g "$RG" --secrets \
  aoai-key='REPLACE_ME'

az containerapp update -n "$APP_NAME" -g "$RG" --set-env-vars \
  AZURE_OPENAI_ENDPOINT='https://YOUR-RESOURCE.openai.azure.com' \
  AZURE_OPENAI_API_KEY=secretref:aoai-key \
  AZURE_OPENAI_DEPLOYMENT='YOUR-DEPLOYMENT-NAME' \
  AZURE_OPENAI_API_VERSION='2024-10-01-preview'
```

## 5) 验证

```bash
FQDN=$(az containerapp show -n "$APP_NAME" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)

echo "https://$FQDN"
curl -fsS "https://$FQDN/health" | cat
curl -fsS "https://$FQDN/api/snapshot" | head
```

## 6) 初始化/重跑 ingest（推荐：Container Apps Job）

`/api/ingest/run` 这类长任务容易被 Ingress 网关超时截断。建议用 ACA Job 跑离线 ingest。

本仓库已提供脚本入口（用于绕开 CLI 对 `-m` 参数的解析问题）：

- `backend/run_ingest.sh`（容器内路径：`/app/backend/run_ingest.sh`）

创建 Job（只需一次）：

```bash
export JOB_NAME=marco-ingest

az containerapp job create \
  -n "$JOB_NAME" \
  -g "$RG" \
  --environment "$ENV_ID" \
  --image "$IMAGE" \
  --trigger-type Manual \
  --replica-timeout 7200 \
  --replica-retry-limit 1 \
  --command sh \
  --args /app/backend/run_ingest.sh \
  --registry-server "$ACR_SERVER" \
  --registry-identity system

# 复用同一套 PG* 环境变量（推荐把密码放 secret）
az containerapp job secret set -n "$JOB_NAME" -g "$RG" --secrets pgpassword='REPLACE_ME'

az containerapp job update -n "$JOB_NAME" -g "$RG" --set-env-vars \
  PGHOST=zgendb.postgres.database.azure.com \
  PGUSER=myadmin \
  PGPORT=5432 \
  PGDATABASE=postgres \
  PGSSLMODE=require \
  PGPASSWORD=secretref:pgpassword

### 每天上午自动跑（Schedule Job）

当前 `marco-ingest` 是手动触发（Manual）。如果你希望每天上午自动跑一次，建议新建一个 Schedule Job（不影响手动 Job）。

建议 cron 用 UTC：默认 `0 23 * * *`（大约是澳洲东部上午；夏令时会偏移 1 小时）。

```bash
export SCHEDULE_JOB_NAME=marco-ingest-daily
export SCHEDULE_CRON='0 23 * * *'

az containerapp job create \
  -n "$SCHEDULE_JOB_NAME" \
  -g "$RG" \
  --environment "$ENV_ID" \
  --image "$IMAGE" \
  --trigger-type Schedule \
  --cron-expression "$SCHEDULE_CRON" \
  --replica-timeout 7200 \
  --replica-retry-limit 1 \
  --command sh \
  --args /app/backend/run_ingest.sh \
  --registry-server "$ACR_SERVER" \
  --registry-identity /subscriptions/96e7862a-aec2-4c4c-aec1-8c7223574a17/resourcegroups/rg-zgen/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uai-35tvmys2nudps-acr

az containerapp job secret set -n "$SCHEDULE_JOB_NAME" -g "$RG" --secrets pgpassword='REPLACE_ME'

az containerapp job update -n "$SCHEDULE_JOB_NAME" -g "$RG" --set-env-vars \
  PGHOST=zgendb.postgres.database.azure.com \
  PGUSER=myadmin \
  PGPORT=5432 \
  PGDATABASE=postgres \
  PGSSLMODE=require \
  PGPASSWORD=secretref:pgpassword
```

如果你使用 [deploy/publish.sh](deploy/publish.sh)，脚本会默认维护该定时 Job（可用 `ENABLE_SCHEDULE_JOB=0` 关闭；也可用 `SCHEDULE_CRON` 覆盖时间）。

启动一次执行：

```bash
EXEC_NAME=$(az containerapp job start -n "$JOB_NAME" -g "$RG" --query name -o tsv)
echo "$EXEC_NAME"
```

查看执行状态：

```bash
az containerapp job execution show -n "$JOB_NAME" -g "$RG" --job-execution-name "$EXEC_NAME" -o table
```

查看执行日志（本环境的 az 扩展不提供 `job execution logs`，用 Log Analytics 查询）：

```bash
WORKSPACE_ID=$(az containerapp env show -n zgen-env -g "$RG" --query properties.appLogsConfiguration.logAnalyticsConfiguration.customerId -o tsv)
az monitor log-analytics query --workspace "$WORKSPACE_ID" \
  --analytics-query "search \"$EXEC_NAME\" | sort by TimeGenerated asc | take 200"
```

如果你希望把 Postgres 也迁到 Azure（Flexible Server）并用私网访问（VNet），需要再补 Private Endpoint / DNS / egress 配置。
把图一的一个人物加到图二的大合照，站后面一排靠左边，不改变样貌，发型和姿势，不能挡着其他人，图二的人物不能动, 把图二后面的红色桌子去掉。真实，自然，不能改变所有人的样貌，发型和衣着。