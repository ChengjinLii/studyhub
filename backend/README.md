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

MCP Gateway 在本地和测试环境默认跟随后端一起启动，Streamable HTTP 入口是：

```text
http://127.0.0.1:8011/mcp
```

生产和预览环境默认不会开放 MCP，需要显式配置后才会挂载：

```bash
STUDYHUB_MCP_ENABLED=true
```

如果开启 MCP 访问鉴权，客户端请求需要附带 Bearer token：

```bash
STUDYHUB_MCP_REQUIRE_AUTH=true
STUDYHUB_MCP_ACCESS_TOKEN=<your-token>
```

MCP 返回的站内 URL 默认使用 `https://study-hub.cn`，可以通过 `STUDYHUB_PUBLIC_SITE_BASE_URL` 改成当前部署域名。

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
我想要数据结构期末复习资料，帮我在 StudyHub 里找几份，并打开最相关的一份看看内容。
```

预期行为：CLI 会先调用 `search` 搜索资料、求购和集市结果，再对最相关的 `material:*` 结果调用 `fetch` 读取详情。

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
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search","arguments":{"query":"数据结构","limit":10}}}'

curl -s http://127.0.0.1:8011/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fetch","arguments":{"id":"material:101"}}}'
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
- ai agent：`local` / `openai-compatible` / `sub2api`

真实密钥、证书、Redis URL、OSS 凭据、支付宝证书路径、KYC 凭据都必须只放在 `private/`。

AI 学习辅导默认可以保持 `local` 兼容回复；如果要接本机 sub2api，生产私有配置示例：

```env
STUDYHUB_AI_AGENT_PROVIDER=sub2api
STUDYHUB_AI_AGENT_BASE_URL=http://127.0.0.1:8787/v1
STUDYHUB_AI_AGENT_API_KEY=CHANGE_ME
STUDYHUB_AI_AGENT_MODEL=gpt-5.4-mini
STUDYHUB_AI_AGENT_TIMEOUT_SECONDS=60
```

学习辅导 Agent 还支持只读记忆上下文和 PDF 页级证据读取。默认不会写入数据库，且有资源上限；生产环境可按服务器余量调整：

```env
STUDYHUB_AI_AGENT_MEMORY_CONTEXT_ENABLED=true
STUDYHUB_AI_AGENT_MEMORY_MAX_MATERIALS=8
STUDYHUB_AI_AGENT_MEMORY_MAX_INTERACTION_CHECKS=6
STUDYHUB_AI_AGENT_PDF_EVIDENCE_ENABLED=true
STUDYHUB_AI_AGENT_PDF_EVIDENCE_MAX_MATERIALS=2
STUDYHUB_AI_AGENT_PDF_EVIDENCE_MAX_PAGES=6
STUDYHUB_AI_AGENT_PDF_EVIDENCE_MAX_BYTES=4194304
STUDYHUB_AI_AGENT_PDF_EXTRACT_CACHE_ENABLED=true
STUDYHUB_AI_AGENT_PDF_EXTRACT_CACHE_MAX_ENTRIES=64
```

Agent 会在后端用轻量规则生成 `query_plan`，用于识别资料推荐、往年常考分析、复习计划、资料总结或错题辅导等意图；该步骤不访问外部服务、不写入数据库。

外部模型输出会经过后端 Safety Harness：只允许推荐候选资料中的 `material_id`，只允许引用已读取的 PDF 页码，并过滤内部上下文字段泄露；不合格输出会回退到本地推荐回答。

PDF 页级证据会尽量抽取年份、题型、题号、知识点线索和来源类型，用于支撑往年常考分析和可核验引用。

Agent 还会从当前请求的候选资料、PDF 证据、`query_plan` 和只读记忆上下文生成临时课程记忆卡片，汇总课程级年份、题型、知识点、页码引用和推荐学习顺序；当前版本不持久化该卡片。

## RESTful API 约定

后端公开接口以 RESTful API 为主，目标是让 Web 前端、外部客户端和后续 MCP 工具可以直接从 OpenAPI 中获得稳定、可解释的资源操作。

设计规则：

- 路径表达资源，不把业务动作直接放进公开路径中。
- HTTP Method 表达操作语义：
  - `GET`：读取资源或资源集合
  - `POST`：创建资源，例如创建订单、创建求购贡献、创建 AI 对话
  - `PUT`：创建或确认一个确定的子资源，例如关注关系、订单确认
  - `PATCH`：局部更新资源或集合，例如批量修改资料元信息、标记通知已读
  - `DELETE`：删除资源、取消关系或取消贡献
- 关系和派生能力使用子资源表达，例如 `/api/users/{id}/follow`、`/api/materials/{id}/downloads`、`/api/requests/{id}/responses`。
- 管理后台批量操作优先放在集合资源上，例如 `PATCH /api/admin/materials`、`DELETE /api/admin/market`。
- 支付、AI、通知、收款码等能力也按资源建模，例如 `/api/alipay-payments`、`/api/ai-chats`、`/api/notifications`、`/api/admin/users/{id}/payout-qr`。

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
POST   /api/ai-chats                        AI 对话
POST   /api/ai-recommendations              AI 推荐
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
