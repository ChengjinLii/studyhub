# ADR-003：Agentic Platform 严格仅限管理员

- 状态：Accepted
- 日期：2026-07-26
- 范围：第一阶段所有 Agentic API、控制台、主动任务和外部工具

## 决定

新平台使用专用 `require_admin_agent_context`，只接受 `ROLE_ADMIN`。`ROLE_DEVELOPER`、普通用户和匿名请求均不能访问。该规则独立于现有 `require_privileged_auth_context`，后者允许 Admin 或 Developer，不能用于新平台。

所有新入口置于 `/api/admin/agent-*` 或 `/api/admin/deep-research`；前端只在管理员控制台展示，且后端始终强制鉴权。Feature Flag 默认关闭，Web/Scholar/Python Tool 默认关闭。主动任务第一阶段只生成管理员可预览的 Artifact，不向学生发送通知、修改学生计划或暴露公开 MCP。

## 后果

- 现有 `/api/ai-*` 行为、现有学习辅导浮窗和公开 MCP 工具不被改动。
- 所有外部网络访问必须经过 allowlist、SSRF/私网地址拒绝、下载/MIME 限制、审计和提示注入清洗。
- 原始模型输出、Artifact 和 Transition 只在管理员授权路径下读取；不记录或展示私有 Chain-of-Thought。
