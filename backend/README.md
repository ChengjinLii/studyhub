# StudyHub Backend

后端位于 `backend/`。目录结构尽量贴近成熟 FastAPI 项目的常见组织方式，方便开源协作者快速定位路由、服务、仓储、provider 和测试代码。

## 目录说明

```text
app/
  api/           路由与依赖注入
  contracts/     契约对比工具
  core/          配置、日志、数据库、异常、响应辅助
  integrations/  资产存储适配层
  models/        SQLAlchemy 模型
  providers/     mail / storage / payment / kyc / lock provider 分层
  repos/         仓储层
  schemas/       Pydantic 模型
  services/      业务服务层
  workers/       worker 入口
tests/           pytest 测试
fixtures/        契约样本与历史兼容样本
artifacts/       本地测试报告与生成产物
scripts/         后端侧辅助脚本
```

## 启动方式

推荐从仓库根目录直接启动整套本地开发环境：

```bash
bash scripts/dev/docker-dev-up.sh
```

如果你只想单独跑后端：

```bash
cd backend
../.venv/bin/pip install -e '.[dev]'
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8011
```

需要本地环境变量样例时：

```bash
cd backend
cp .env.example .env
```

## local-dev 的行为

`local-dev` 主要服务开源协作者，设计目标是“好启动、可调试、边界清晰”：

- 不依赖 `private/`
- Docker local-dev 默认接本地 MySQL
- shell quickstart 默认接本地 SQLite
- 本地文件、收款码、邮件 outbox 写入 `.local-dev/` 或 `.local-dev-docker/`
- 仓库会预置一个开发账号，并提供 `POST /api/auth/dev-login`

默认开发账号：

- 用户名：`developer`
- 密码：`developer123`
- 邮箱：`developer@local.studyhub.dev`

## Provider 分层

后端已经把主要外部依赖拆成 provider 层：

- mail：`local_outbox` / `smtp`
- storage：`local_fs` / `oss`
- payment：`local_alipay` / `alipay_page`
- payout transfer：`local_transfer` / `alipay_transfer`
- kyc：`mock_local` / `aliyun_cloud_auth`
- lock：`db_row` / `redis`

真实密钥、证书、Redis URL、OSS 凭据、支付宝证书路径、KYC 凭据都必须只放在 `private/`。

## 当前已经做的性能优化

结合 StudyHub 当前以公开读流量为主的特点，后端先做了这几类收益稳定的优化：

- 保持 FastAPI 默认的高效 JSON 序列化路径
- 启用了 `GZipMiddleware`
- 给匿名公开读接口加了短 TTL 缓存；未配置 Redis 时走本地进程缓存，配置 Redis 后可切到跨进程共享缓存
- `/api/materials/column` 支持 `ETag` / `304`
- 健康检查和指标接口默认跳过普通访问日志
- 求购超时推进这类维护逻辑继续由 worker 驱动，避免公开读请求顺手做后台工作

这些优化为什么适合现在这个项目：

- 资料列表、推荐、集市、榜单、评论等接口有大量重复匿名读取
- 返回体主要是 JSON，序列化和压缩优化能直接生效
- 热点缓存先做成本地 / Redis 双后端，不急着一开始就引入更重的复杂度

## 后续仍值得继续做的优化

如果继续往下压性能，优先级比较高的方向有：

- 把一部分热点只读链路迁到真正的异步数据库访问
- 继续优化少数长尾查询和更复杂的管理后台读链路
- 把更重的资产处理、报表生成、外部回调处理进一步移到 worker

## 常用验证接口

```bash
curl http://127.0.0.1:8111/api/healthz
curl http://127.0.0.1:8111/api/readyz
curl http://127.0.0.1:8111/api/metrics
curl "http://127.0.0.1:8111/api/materials/column?topic=experience&page=1&size=2"
curl -X POST http://127.0.0.1:8111/api/auth/dev-login -i
```

## 测试

```bash
cd backend
../.venv/bin/pytest
```

## Contract Diff

```bash
cd backend
../.venv/bin/python scripts/contract_diff.py \
  --candidate-base-url http://127.0.0.1:8011 \
  --sample-dir fixtures/contracts \
  --output-dir artifacts/contract-diff
```

如果你想和另一套正在运行的 StudyHub FastAPI 实例做对比：

```bash
cd backend
../.venv/bin/python scripts/contract_diff.py \
  --candidate-base-url http://127.0.0.1:8011 \
  --baseline-base-url http://127.0.0.1:8112 \
  --sample-dir fixtures/contracts \
  --output-dir artifacts/contract-diff
```

## 约束

- 后端代码、测试、fixtures 应保持自洽
- 运行时不依赖 Spring Boot 基线仓库中的文件
- `private/` 只给 preview / production
- preview / production 不应隐式回退到本地 fake provider
- 默认脚本不负责对真实 MySQL / OSS / Redis / SMTP / 支付宝 / KYC 做破坏性测试
