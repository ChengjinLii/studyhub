# StudyHub FastAPI Backend

后端代码集中在 `backend/`。目录布局参考成熟 FastAPI 项目的常见组织方式：`app/` 放业务代码，`tests/` 放 pytest，`fixtures/` 放契约和本地种子，`artifacts/` 放本地产物。

## 目录

```text
app/
  api/           路由与依赖注入
  contracts/     契约对比框架
  core/          配置、日志、数据库、异常、响应壳
  integrations/  外部适配器占位
  providers/     mail / storage / payment provider 分层
  models/        SQLAlchemy 模型
  repos/         仓储层
  schemas/       Pydantic schema
  services/      服务层
  workers/       worker 入口
tests/           pytest
fixtures/        契约样本、历史兼容样本、本地 seed
artifacts/       契约对比报告等本地产物
scripts/         后端侧辅助脚本
```

## 推荐运行方式

优先从仓库根目录启动：

```bash
cd /root/StudyHub-FastAPI
bash scripts/docker-dev-up.sh
```

这时后端会运行在：

- `http://127.0.0.1:8111`

当前 `local-dev` 的关键行为：

- 不读取 `private/` 里的真实生产密钥
- `docker compose` 下数据库走本地 `MySQL`
- shell quickstart 下数据库走本地 `SQLite`
- 本地文件、收款码、邮件 outbox 都落在 `.local-dev-docker/` 或 `.local-dev/`
- 会自动预置 `developer` 账号
- `POST /api/auth/dev-login` 可直接写入正常登录 Cookie

生产相关补充：

- `preview / production` 默认不会在应用启动时自动建表
- 如果 schema 不完整，应用会在启动前失败，而不是偷偷 `create_all`
- 真正的建表、备份、恢复要走仓库根目录 `scripts/` 下的显式运维脚本
- `production` 禁止通过脚本自动建表或恢复数据库

## Preview / Production provider

后端现在已经具备这些 provider 入口：

- mail: `local_outbox` / `smtp`
- storage: `local_fs` / `oss`
- payment: `local_alipay` / `alipay_page`
- payout transfer: `local_transfer` / `alipay_transfer`
- kyc: `mock_local` / `aliyun_cloud_auth`
- lock: `db_row` / `redis`

这些 provider 的真实密钥、证书、Redis URL、OSS AK/SK、Alipay 私钥/公钥路径、KYC 凭据都必须只放在 `private/` 下。

## 开发方式选择

- 如果你要长期开发、排查数据库语义、尽量贴近真实环境，优先用仓库根目录的 `docker compose`
- 如果你只是想快速把后端跑起来，或者临时调一个接口，可以退回 shell `quickstart`
- 两者最大的区别是：`docker compose` 默认走本地 `MySQL`，shell `quickstart` 默认走本地 `SQLite`

## 手动启动

如果你要绕开 `docker compose` 单独跑后端：

```bash
cd /root/StudyHub-FastAPI/backend
/root/StudyHub-FastAPI/.venv/bin/pip install -e '.[dev]'
/root/StudyHub-FastAPI/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8011
```

建议先准备环境样例：

```bash
cd /root/StudyHub-FastAPI/backend
cp .env.example .env
```

## 基本验证

```bash
curl http://127.0.0.1:8111/api/healthz
curl http://127.0.0.1:8111/api/readyz
curl http://127.0.0.1:8111/api/metrics
curl http://127.0.0.1:8111/api/materials/column?topic=experience&page=1&size=2
curl -X POST http://127.0.0.1:8111/api/auth/dev-login -i
```

## 测试

```bash
cd /root/StudyHub-FastAPI/backend
/root/StudyHub-FastAPI/.venv/bin/pytest
```

## Contract Diff

```bash
cd /root/StudyHub-FastAPI/backend
/root/StudyHub-FastAPI/.venv/bin/python scripts/contract_diff.py \
  --candidate-base-url http://127.0.0.1:8011 \
  --sample-dir fixtures/contracts \
  --output-dir artifacts/contract-diff
```

如果需要拿另一套正在运行的 StudyHub FastAPI 基线做在线对比：

```bash
/root/StudyHub-FastAPI/.venv/bin/python scripts/contract_diff.py \
  --candidate-base-url http://127.0.0.1:8011 \
  --baseline-base-url http://127.0.0.1:8112 \
  --sample-dir fixtures/contracts \
  --output-dir artifacts/contract-diff
```

## 约束

- `backend/` 的代码、测试、fixtures 应该自洽，不依赖旧仓库运行时文件
- `private/` 只给 preview / production
- `local-dev` 不是生产环境，但也不应该偷偷回退到 `private/`
- `preview / production` 只允许使用显式配置的真实 provider，不能隐式回退到本地 provider
- 对现有真实 MySQL / OSS / Redis / SMTP / 支付宝 / KYC 的破坏性测试不属于本仓库默认脚本范畴
