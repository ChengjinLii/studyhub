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
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8011
```

修改 `backend/pyproject.toml` 后，运行 `bash scripts/deps/update-backend-lock.sh` 更新哈希锁文件。

MCP Gateway 在本地和测试环境默认跟随后端一起启动，Streamable HTTP 入口是：

```text
http://127.0.0.1:8011/mcp
```

生产和预览环境默认不会开放 MCP，需要显式配置后才会挂载：

```bash
STUDYHUB_MCP_ENABLED=true
```

对外 MCP 只注册四个只读工具：`materials.search`、`materials.get`、`materials.recommend`、`platform.policy`。求购、集市、榜单、用户、OpenAPI、写操作、管理工具和健康检查均不注册，也不能通过 resources/prompts 绕过工具边界。

生产环境推荐把 StudyHub 作为 OAuth 2.1 Resource Server，接入现有授权服务器，通过 issuer、audience 和 JWKS 验证访问令牌：

```bash
STUDYHUB_MCP_REQUIRE_AUTH=true
STUDYHUB_MCP_AUTH_MODE=oauth
STUDYHUB_MCP_OAUTH_AUTHORIZATION_SERVERS=https://auth.example.edu
STUDYHUB_MCP_OAUTH_ISSUER=https://auth.example.edu
STUDYHUB_MCP_OAUTH_JWKS_URI=https://auth.example.edu/.well-known/jwks.json
STUDYHUB_MCP_OAUTH_AUDIENCE=https://study-hub.cn/mcp
STUDYHUB_MCP_CLIENT_RATE_LIMIT=60
STUDYHUB_MCP_CLIENT_QUOTA=1000
STUDYHUB_MCP_CLIENT_QUOTA_WINDOW_SECONDS=86400
```

`hybrid` 可用于 OAuth 迁移期；`static` 只建议本地开发或短期兼容。旧的 discovery/recommend/summary scope 在迁移期仍能匹配对应新工具，但 Protected Resource Metadata 只发布新的最小 scope。

MCP 返回的站内 URL 默认使用 `https://study-hub.cn`，可以通过 `STUDYHUB_PUBLIC_SITE_BASE_URL` 改成当前部署域名。
MCP 对外定位为资料发现和导流入口，只返回公开资料摘要和 StudyHub 站内链接；不会返回下载链接、网盘链接、提取码、文件 token 或完整预览内容。用户需要打开 StudyHub 链接后，按站内正常流程登录、购买或下载。

OAuth Protected Resource Metadata：

```text
http://127.0.0.1:8011/.well-known/oauth-protected-resource
http://127.0.0.1:8011/.well-known/oauth-protected-resource/mcp
```

完整外部接入说明见仓库根目录 [`MCP.md`](../MCP.md)。

用 MCP Inspector 验证：

```bash
npx -y @modelcontextprotocol/inspector http://127.0.0.1:8011/mcp
```

接入支持 MCP Streamable HTTP 的本地 CLI 时，把 StudyHub 配成一个 HTTP MCP server：

```json
{
  "mcpServers": {
    "studyhub": {
      "type": "http",
      "url": "http://127.0.0.1:8011/mcp"
    }
  }
}
```

如果 CLI 支持命令式添加 MCP server，也可以按同样的信息添加：

```bash
<your-cli> mcp add studyhub --transport http --url http://127.0.0.1:8011/mcp
```

接入后可以直接用自然语言测试，例如：

```text
我想要数据结构期末复习资料，帮我在 StudyHub 里找几份，并把最相关的资料链接推荐给我。
```

预期行为：CLI 调用 `materials.search` 或 `materials.recommend`，返回轻量资料元数据、推荐理由和 StudyHub 站内链接。后续下载、购买、打赏等动作必须由用户打开链接后在 StudyHub 站内完成。

也可以直接用 JSON-RPC 验证：

```bash
curl -s http://127.0.0.1:8011/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <your-token>' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

curl -s http://127.0.0.1:8011/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <your-token>' \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"materials.search","arguments":{"query":"期末 真题","course":"数据结构","limit":5}}}'

curl -s http://127.0.0.1:8011/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <your-token>' \
  --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"materials.recommend","arguments":{"query":"基础一般","course":"通信原理","goal":"两周后期末考试","time_budget":"14 天，每天 2 小时","limit":3}}}'
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

评论写操作使用 Nginx 和 Redis 双层防滥用保护。发布评论同时受 IP、用户分钟额度和用户小时额度约束；编辑、删除、点赞及举报按用户和动作独立计数。相同用户在同一资料或回复下重复提交相同内容时，Redis 会保留短期去重键；Redis 不可用时使用有容量上限的进程内缓存，不写入业务数据库。相关生产参数：

```env
STUDYHUB_RATE_LIMIT_COMMENT_CREATE_USER_MINUTE=6
STUDYHUB_RATE_LIMIT_COMMENT_CREATE_USER_HOUR=30
STUDYHUB_RATE_LIMIT_COMMENT_CREATE_IP_MINUTE=60
STUDYHUB_RATE_LIMIT_COMMENT_ACTION_USER_MINUTE=30
STUDYHUB_RATE_LIMIT_COMMENT_REPORT_USER_HOUR=10
STUDYHUB_RATE_LIMIT_COMMENT_DUPLICATE_SECONDS=300
STUDYHUB_COMMENTS_WRITE_ENABLED=true
```

遇到集中攻击时，可临时设置 `STUDYHUB_COMMENTS_WRITE_ENABLED=false` 并重启后端，使评论区进入只读模式；评论列表仍可访问，且不会修改或删除已有评论数据。

旧站内 Agent 的动态工具、编排、记忆、页级证据和模型路由已经从后端运行时移除。RAG 检索实验保留在独立的 `studyhub-agent/ai_platform/rag_experiments/`，不由本服务导入；后续 Agent V2 集成不得绕过这里已有的用户权限、资料可见性、订单和下载授权边界。

## RESTful API 约定

后端公开接口以 RESTful API 为主，目标是让 Web 前端、外部客户端和后续 MCP 工具可以直接从 OpenAPI 中获得稳定、可解释的资源操作。

设计规则：

- 路径表达资源，不把业务动作直接放进公开路径中。
- HTTP Method 表达操作语义：
  - `GET`：读取资源或资源集合
  - `POST`：创建资源，例如创建订单或创建求购贡献
  - `PUT`：创建或确认一个确定的子资源，例如关注关系、订单确认
  - `PATCH`：局部更新资源或集合，例如批量修改资料元信息、标记通知已读
  - `DELETE`：删除资源、取消关系或取消贡献
- 关系和派生能力使用子资源表达，例如 `/api/users/{id}/follow`、`/api/materials/{id}/downloads`、`/api/requests/{id}/responses`。
- 管理后台批量操作优先放在集合资源上，例如 `PATCH /api/admin/materials`、`DELETE /api/admin/market`。
- 支付、通知、收款码等能力也按资源建模，例如 `/api/alipay-payments`、`/api/notifications`、`/api/admin/users/{id}/payout-qr`。

兼容策略：

- 历史动作型路径仍保留可用，避免旧前端版本或外部调用突然失效。
- 旧路径会通过 `include_in_schema=False` 从 OpenAPI 中隐藏。
- 新客户端、MCP 代码和文档应只依赖 OpenAPI 暴露的 RESTful 路径。
- 如果必须新增非 RESTful 兼容路径，需要同时提供 RESTful canonical 路径，并补充测试确认它出现在 OpenAPI 中。

典型映射：

```text
POST   /api/session                         登录
DELETE /api/session                         登出
GET    /api/captchas                        获取验证码
POST   /api/registration-verifications      发送注册验证码
POST   /api/registrations                   完成注册
POST   /api/materials/{id}/downloads        生成资料下载授权
PUT    /api/materials/{id}/like             点赞资料
POST   /api/requests/{id}/contributions     跟购求购
PUT    /api/requests/{id}/accepted-response 采纳求购应答
PATCH  /api/notifications                   标记通知已读
```

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
