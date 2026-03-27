# studyhub scripts

这里收敛两套启动方式：

- 推荐：`docker compose` 的 `local-dev`
- 备用：纯 shell 的 `quickstart`
- 真实链路：`preview / production / worker / scheduler / db ops`

如果你是开源协作者，优先使用 `docker compose`。这样数据库会切到本地 MySQL，和生产语义更接近，也不用自己手动装依赖。

## 两种方式的区别

### `docker compose local-dev`

- 推荐给真正要参与开发的人
- 数据库是本地 `MySQL`
- 前端、后端和依赖一起启动，环境更统一
- 更接近真实开发环境
- 需要先安装 Docker

### shell `quickstart`

- 推荐给只想快速跑起来看看的人
- 数据库默认是本地 `SQLite`
- 不需要 Docker，直接本机跑 Python 和 Node
- 启动更轻、更快
- 更适合快速体验、UI 调试和临时联调

建议：

- 长期开发：用 `docker compose`
- 快速体验：用 shell `quickstart`

## 推荐方式：Docker Compose Local Dev

根目录已经提供：

- `docker-compose.yml`
- `scripts/docker-dev-up.sh`
- `scripts/docker-dev-down.sh`
- `scripts/docker-dev-status.sh`
- `scripts/docker-dev-logs.sh`

### 启动

```bash
bash scripts/docker-dev-up.sh
```

等价原生命令：

```bash
docker compose up -d --build
```

### 状态

```bash
bash scripts/docker-dev-status.sh
```

### 日志

```bash
bash scripts/docker-dev-logs.sh
```

只看某个服务：

```bash
bash scripts/docker-dev-logs.sh backend
```

### 停止

```bash
bash scripts/docker-dev-down.sh
```

等价原生命令：

```bash
docker compose down
```

### 访问地址

- frontend: `http://127.0.0.1:3100`
- backend health: `http://127.0.0.1:8111/api/healthz`
- mysql: `127.0.0.1:3307`

### 初始账号

- username: `developer`
- password: `developer123`
- email: `developer@local.studyhub.dev`

登录方式：

- 打开登录页后点击 `Local Dev` 快捷入口
- 或直接请求 `POST /api/auth/dev-login`

### 当前 compose local-dev 的能力边界

当前 `docker compose` 版本已经做到：

- 数据库：本地 `MySQL`
- 前端：`Next.js dev server`
- 后端：`FastAPI + uvicorn --reload`

当前仍然是本地替代实现：

- mail: `local_outbox`
- storage: `local_fs`
- payment: `local_alipay`

也就是说，`docker compose` 这套已经比 shell quickstart 更接近真实开发，但还不是完整生产依赖仿真。

### 运行产物

- backend 本地资产 / outbox：`.local-dev-docker/`
- mysql 数据：compose named volume `mysql-data`

## 备用方式：Shell Quickstart

这套方式更轻，但数据库仍然是 SQLite，更适合快速看界面、UI 调试或临时联调。

### 前置条件

- Python 虚拟环境已准备好：`.venv`
- 前端依赖已安装：`cd frontend && npm install`
- 如需后端开发依赖：`cd backend && ../.venv/bin/pip install -e '.[dev]'`

### 默认端口

- backend: `127.0.0.1:8011`
- frontend: `127.0.0.1:3000`

可通过环境变量覆盖：

- `LOCAL_DEV_BACKEND_PORT`
- `LOCAL_DEV_FRONTEND_PORT`
- `STUDYHUB_LOCAL_DEV_ROOT_DIR`

### 当前服务器建议端口

这台机器上已经有正式站和预览站在运行，shell 方式建议使用：

- backend: `127.0.0.1:8111`
- frontend: `127.0.0.1:3100`
- root dir: `./.runtime/local-dev-shell`

### 启动

```bash
bash scripts/local-dev-up.sh
```

后台运行示例：

```bash
mkdir -p ./.runtime/local-dev-shell
nohup env \
  LOCAL_DEV_BACKEND_PORT=8111 \
  LOCAL_DEV_FRONTEND_PORT=3100 \
  STUDYHUB_LOCAL_DEV_ROOT_DIR=./.runtime/local-dev-shell \
  bash scripts/local-dev-up.sh \
  >./.runtime/local-dev-shell/launcher.log 2>&1 &
```

### 停止

```bash
env \
  LOCAL_DEV_BACKEND_PORT=8111 \
  LOCAL_DEV_FRONTEND_PORT=3100 \
  STUDYHUB_LOCAL_DEV_ROOT_DIR=./.runtime/local-dev-shell \
  bash scripts/local-dev-down.sh
```

### 查看状态

```bash
env \
  LOCAL_DEV_BACKEND_PORT=8111 \
  LOCAL_DEV_FRONTEND_PORT=3100 \
  STUDYHUB_LOCAL_DEV_ROOT_DIR=./.runtime/local-dev-shell \
  bash scripts/local-dev-status.sh
```

### Quickstart 当前 provider

- mail: `local_outbox`
  - 验证邮件写入 `STUDYHUB_LOCAL_DEV_ROOT_DIR/outbox/mail/`
- storage: `local_fs`
  - 资料、集市、收款码资产写入 `STUDYHUB_LOCAL_DEV_ROOT_DIR/`
- payment: `local_alipay`
  - 支付表单、主动查询、回调都走本地 provider

## Preview / Production / Worker

这几套脚本不是给开源协作者默认使用的，而是给仓库维护者在 **隔离 preview 资源** 或 **真实 production 资源** 上使用。

前提：

- `private/.env.preview` 或 `private/.env.production` 已准备好
- 所有敏感配置、证书、密钥都只放在 `private/`
- preview 只能连隔离库 / 隔离 bucket / 隔离 Redis / 测试 SMTP / 测试商户
- production 不允许回退到 SQLite、`local_fs`、`local_outbox`、`local_alipay`、`local_transfer`、`mock_local`、`db_row`

### Preview

```bash
bash scripts/preview-up.sh
bash scripts/preview-status.sh
bash scripts/preview-smoke.sh
bash scripts/preview-down.sh
```

默认端口：

- backend: `127.0.0.1:8211`
- frontend: `127.0.0.1:3200`

### Production

```bash
bash scripts/production-up.sh
bash scripts/production-status.sh
bash scripts/production-smoke.sh
bash scripts/production-down.sh
```

默认端口：

- backend: `127.0.0.1:8311`
- frontend: `127.0.0.1:3300`

### Worker / Scheduler

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/worker-up.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/worker-status.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/worker-down.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/scheduler-up.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/scheduler-status.sh
STUDYHUB_ENVIRONMENT=preview bash scripts/scheduler-down.sh
```

可选环境变量：

- `WORKER_JOB=all|settlement|request-refund|payout-transfer`
- `WORKER_INTERVAL_SECONDS=60`

### Health Check

```bash
bash scripts/healthcheck.sh http://127.0.0.1:8211
```

### Database Ops

这些脚本的设计目标是“显式、保守、默认只读”。也就是说：

- 应用启动不会自动建表
- 建表必须单独确认
- 备份是允许的
- 恢复默认只允许 preview / local-dev，不允许 production

#### 只读检查

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db-check.sh
```

#### preview 显式建表

```bash
ALLOW_PREVIEW_DB_CREATE=I_UNDERSTAND_CREATE_SCHEMA \
STUDYHUB_ENVIRONMENT=preview \
bash scripts/db-init-schema.sh
```

#### 数据库备份

```bash
STUDYHUB_ENVIRONMENT=preview bash scripts/db-backup.sh
STUDYHUB_ENVIRONMENT=production bash scripts/db-backup.sh private/backups/manual-prod.sql.gz
```

#### preview 恢复

```bash
YES_PREVIEW_DB_RESTORE=I_UNDERSTAND_RESTORE \
STUDYHUB_ENVIRONMENT=preview \
bash scripts/db-restore-preview.sh /path/to/preview-backup.sql.gz
```

生产环境默认不提供 restore 脚本入口。

### Observability

后端默认提供：

- `GET /api/healthz`
- `GET /api/readyz`
- `GET /api/metrics`

其中：

- `healthz` 适合最小连通性检查
- `readyz` 适合查看数据库和 provider 是否 ready
- `metrics` 提供基础 Prometheus 文本指标：`studyhub_app_info`、HTTP 请求计数/耗时、worker job 计数/耗时

### 硬约束提醒

- 不允许修改外部 Spring Boot 基线仓库
- 不允许用这些脚本对现有生产 MySQL / OSS / Redis / SMTP / 支付宝 / KYC 做破坏性测试
- 所有敏感配置、证书、密钥都只能放在 `private/`
- 真实写链路应先在隔离 preview 资源完成，不应直接对现有 production 资源试写
