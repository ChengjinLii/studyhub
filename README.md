# studyhub

StudyHub 的 FastAPI 重构仓库。目录组织参考 `fastapi/full-stack-fastapi-template`，把后端、前端、脚本和本地文档分开管理。

GitHub 仓库：
- FastAPI 主仓库：`https://github.com/ChengjinLii/studyhub`
- Spring Boot 基线仓库：`https://github.com/ChengjinLii/studyhub-springboot`

## 目录

```text
backend/   FastAPI 后端、pytest、fixtures、contract diff
frontend/  Next.js 前端
scripts/   docker compose / quickstart 启停脚本与说明
docs/      本地迁移与设计文档（git ignore）
private/   仅供 preview / production 使用的私密配置与运行资产（git ignore）
```

## 推荐开发方式

推荐用 `docker compose` 跑本地开发环境：

```bash
bash scripts/docker-dev-up.sh
```

启动后：

- frontend: `http://127.0.0.1:3100`
- backend: `http://127.0.0.1:8111/api/healthz`
- mysql: `127.0.0.1:3307`

默认开发账号：

- username: `developer`
- password: `developer123`
- email: `developer@local.studyhub.dev`

当前这套 `docker compose local-dev` 的定位是“近生产开发环境”：

- 数据库：本地 `MySQL`
- 前端：`Next.js dev server`
- 后端：`FastAPI + uvicorn --reload`

当前仍然保留本地替代 provider：

- mail: `local_outbox`
- storage: `local_fs`
- payment: `local_alipay`

也就是说，它已经比纯 shell 启动更接近真实开发，但还没有接真实 SMTP / OSS / 支付宝 / KYC。

## 两种方式的区别

### 1. `docker compose local-dev`

- 推荐给真正要参与开发的人
- 数据库是本地 `MySQL`
- 前端、后端和依赖一起启动，环境更统一
- 更接近真实生产行为，适合长期开发、联调和排查问题
- 前提是本机安装了 Docker

### 2. shell `quickstart`

- 推荐给只想先把项目跑起来看看的人
- 数据库默认是本地 `SQLite`
- 不需要 Docker，直接本机跑 Python 和 Node
- 更轻、更快，但和真实生产环境差距更大
- 更适合快速体验、UI 调试和临时联调

简单理解：

- 想认真开发，用 `docker compose`
- 想先快速看看，用 shell `quickstart`

## 备用方式

如果暂时不使用 Docker，可以退回 shell quickstart：

```bash
bash scripts/local-dev-up.sh
```

这套方式更轻，但数据库默认还是 `SQLite`，更适合快速体验、UI 调试和临时联调。

完整说明见：

- [scripts/README.md](scripts/README.md)

## Preview / Production 运行入口

当你已经在 `private/` 准备好隔离的 preview 配置或真实 production 配置后，可以使用：

- `bash scripts/preview-up.sh`
- `bash scripts/preview-status.sh`
- `bash scripts/preview-down.sh`
- `bash scripts/production-up.sh`
- `bash scripts/production-status.sh`
- `bash scripts/production-down.sh`
- `bash scripts/worker-up.sh`
- `bash scripts/worker-status.sh`
- `bash scripts/worker-down.sh`
- `bash scripts/scheduler-up.sh`
- `bash scripts/scheduler-status.sh`
- `bash scripts/scheduler-down.sh`
- `bash scripts/db-check.sh`
- `bash scripts/db-backup.sh`
- `bash scripts/preview-smoke.sh`
- `bash scripts/production-smoke.sh`

这些脚本都会优先读取 `private/.env.preview` 或 `private/.env.production`，并遵守仓库文档里的硬约束：不允许回退到 SQLite，不允许继续偷用本地 provider，也不应直接拿现有生产资源做破坏性测试。

补充说明：

- `preview-up.sh` / `production-up.sh` 启动前只会做数据库连通性与 schema 完整性检查，不会偷偷执行 `create_all`
- 如果需要在隔离 preview 库显式建表，只能使用 `bash scripts/db-init-schema.sh`，而且必须显式确认
- 数据库恢复脚本只提供 `bash scripts/db-restore-preview.sh`，默认不允许对 production 执行 restore
- 后端额外暴露了：
  - `GET /api/readyz`
  - `GET /api/metrics`
  用于 preview / production 的只读健康检查与指标采集

## 仓库约束

- `docs/` 只放本地工作文档，不进入开源仓库
- `private/` 只留给 preview / production，不是开源开发前置条件
- `local-dev` 不应依赖 `private/`
- 当前本地运行资产主要落在 `.local-dev/` 或 `.local-dev-docker/`

## 子目录说明

- [backend/README.md](backend/README.md)
- [frontend/README.md](frontend/README.md)
- [scripts/README.md](scripts/README.md)
