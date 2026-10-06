<div align="center">

# StudyHub

**面向高校的知识共享与校园互助平台**

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](#技术栈)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js-000000?logo=nextdotjs&logoColor=white)](#技术栈)
[![TypeScript](https://img.shields.io/badge/Language-TypeScript-3178C6?logo=typescript&logoColor=white)](#技术栈)
[![MySQL + OSS](https://img.shields.io/badge/Data-MySQL_%2B_OSS-2563eb)](#技术栈)
[![Redis + Worker](https://img.shields.io/badge/Runtime-Redis_%2B_Worker-dc2626)](#技术栈)
[![Qwen](https://img.shields.io/badge/Agent-Qwen3.5--4B_%2F_9B-2563eb)](#studyhub-agent)
[![SGLang](https://img.shields.io/badge/Serving-SGLang-15803d)](#studyhub-agent)
[![PyTorch](https://img.shields.io/badge/AI-PyTorch_%2B_Transformers-EE4C2C?logo=pytorch&logoColor=white)](#技术栈)
[![Qwen3Guard](https://img.shields.io/badge/Text-Qwen3Guard--0.6B-0f766e)](#studyhub-review-jev)
[![OneJev](https://img.shields.io/badge/Vision-OneJev--4B_%2F_9B-c2410c)](#studyhub-review-jev)
[![Website](https://img.shields.io/badge/Website-study--hub.cn-111827)](https://study-hub.cn)
[![MIT](https://img.shields.io/badge/License-MIT-22c55e)](LICENSE)

[功能概览](#功能概览) | [快速开始](#快速开始) | [技术栈](#技术栈) | [Agent](#studyhub-agent) | [内容审核](#studyhub-review-jev) | [ENG](README.en.md)

</div>

StudyHub 连接学习资料、经验分享与校园互助，围绕高校学生的学习和生活需求，提供资源共享、求购协作与校园集市服务。

**分享知识，交流经验，让校园资源更容易找到。**

---

## 功能概览

![StudyHub 海报](assets/studyhub-poster.png)

| 场景 | 主要功能 |
| --- | --- |
| 资料共享 | 上传、浏览与获取课程资料、复习提纲和学习笔记 |
| 经验分享 | 沉淀学习经验、选课建议与校园生活内容 |
| 求购协作 | 发布资源需求，开展求购、互助与交换 |
| 校园集市 | 发布校内二手交易与校园信息 |

官网：[study-hub.cn](https://study-hub.cn)

---

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端服务 | FastAPI、SQLAlchemy、Pydantic Settings、Uvicorn |
| 前端界面 | Next.js 14、React、TypeScript |
| 数据存储 | MySQL、SQLite、阿里云 OSS |
| 缓存与任务 | Redis、BackgroundTasks、独立 Worker |
| 异步处理 | 局部异步数据库访问与异步 I/O |
| 部署运维 | Docker Compose、systemd、Nginx |
| Agent | Qwen3.5-4B / 9B、SGLang、tokenizers、统一 Agent 执行器 |
| 内容审核 | Qwen3Guard-Gen-0.6B、OneJev-4B / 9B、PyTorch、Transformers |

MySQL 用于预览与生产环境，SQLite 用于本地开发和快速体验。

---

## 仓库结构

```text
studyhub/
  backend/          # 后端服务、测试与运维辅助代码
  frontend/         # 前端应用与 PWA
  studyhub-agent/   # Agent 运行框架
  review-jev/       # 文字与图片审核组件
  docs/             # 项目技术文档
  reports/          # 技术报告与项目复盘
  scripts/          # 开发、部署与运维脚本
```

---

## 快速开始

推荐使用 **Python 3.12、Node.js 22、npm 10**，版本配置见 `.python-version` 与 `.nvmrc`。

### Docker 开发环境

```bash
bash scripts/dev/docker-dev-up.sh
```

### 本地轻量环境

```bash
bash scripts/dev/local-dev-up.sh
```

### 模块文档

| 模块 | 说明 |
| --- | --- |
| [后端服务](backend/README.md) | 环境配置、接口与测试 |
| [前端应用](frontend/README.md) | 页面开发、构建与 PWA |
| [Agent](studyhub-agent/README.md) | 工具调用、运行契约与模型推理 |
| [内容审核](review-jev/README.md) | 模型分流、审核接口与批量评测 |
| [开发脚本](scripts/README.md) | 本地启动、部署与运维 |

---

## 接口设计

公开 API 采用 RESTful 风格，资源以复数名词命名，使用 HTTP Method 表达操作。

| 场景 | 接口示例 |
| --- | --- |
| 登录会话 | `POST /api/session` |
| 退出登录 | `DELETE /api/session` |
| 下载授权 | `POST /api/materials/{id}/downloads` |

历史动作型路径保留兼容，新客户端优先使用 OpenAPI 中的资源接口。智能体接入、OAuth 权限范围与配额见 [MCP 接口说明](MCP.md)。

---

## 开发与部署

### 提交前检查

```bash
bash scripts/check-shell-scripts.sh
${STUDYHUB_PYTHON_BIN:-.venv/bin/python} -m ruff check backend/app backend/tests
${STUDYHUB_PYTHON_BIN:-.venv/bin/python} -m pytest backend/tests
npm --prefix frontend run check
npm --prefix frontend run test:unit
```

### 发布检查

```bash
bash scripts/predeploy-check.sh
```

发布采用独立 Release 构建、验证与切换流程。完成首次配置后，使用 `bash scripts/deploy/atomic-release.sh <commit>`，避免直接在在线目录构建前端。

CI 与本地质量检查可使用 `bash scripts/ci-check.sh`。完整门禁包含开发及生产构建下的 Playwright 关键路径，部署配置与运维命令见 [脚本文档](scripts/README.md)。

### 生产配置

生产和预览环境默认关闭 FastAPI 接口文档，需要时通过 `STUDYHUB_DOCS_ENABLED=true` 开启。域名白名单使用 `STUDYHUB_TRUSTED_HOSTS`，可信代理使用 `STUDYHUB_TRUSTED_PROXY_IPS`，按实际部署环境配置。

---

## 参与贡献

欢迎通过 Issue 和 Pull Request 参与项目改进。

### 主要贡献者

| 贡献者 | 姓名 |
| --- | --- |
| [@ChengjinLii](https://github.com/ChengjinLii) | 李承锦 |
| [@Sgt-Friedrich](https://github.com/Sgt-Friedrich) | 曾逸帆 |

### 其他贡献者

| 贡献者 | 姓名 |
| --- | --- |
| [@JoeyLam2005](https://github.com/JoeyLam2005) | 林俊宇 |
| [@xiaji](https://github.com/xiaji) | 季文君 |

初版 SpringBoot 实现见 [studyhub-springboot](https://github.com/ChengjinLii/studyhub-springboot)，目前为内部仓库。

---

## StudyHub Agent

**面向高校学习场景的工具调用 Agent。**

[StudyHub Agent](studyhub-agent/README.md) 以 Qwen3.5-4B 为主要模型，围绕资料检索、预览阅读、平台政策问答与学习记忆构建 Agent 能力，支持 4B / 9B 单模型运行与小到大模型级联。

| 能力 | 实现 |
| --- | --- |
| 工具调用 | 统一执行器，支持检索、推荐、阅读、政策查询与记忆读写 |
| 架构编排 | ReAct、引用核查、规划后执行、上下文压缩与模型级联 |
| 引用核查 | `react_verify` 检查引用页的读取记录，并支持反馈纠正 |
| 运行契约 | 统一消息渲染、调用解析、预算控制与契约哈希 |
| 轨迹记录 | 保存消息、工具证据、架构决策与模型信息 |
| 推理接口 | 支持 SGLang token 级接口和 OpenAI-compatible 接口 |

技术栈：**Python 3.12、Pydantic、Jinja2、httpx、SGLang**。架构与使用方法见 [Agent 文档](studyhub-agent/README.md)。

---

## StudyHub Review-Jev

**面向文字与图片投稿的内容审核组件。**

[StudyHub Review-Jev](review-jev/README.md) 基于 OneJev 构建，支持资料、经验、评论、求购与集市等投稿场景，提供合规风险筛查、版权辅助分析和结构化审核结果。

| 内容类型 | 默认模型 |
| --- | --- |
| 纯文字 | Qwen3Guard-Gen-0.6B |
| 图片或图文 | OneJev-4B |
| 低置信度升级 | OneJev-4B → OneJev-9B → 人工审核 |

审核组件提供 **FastAPI 服务、JSON 命令行、可配置规则与批量评测工具**，覆盖内容风险、隐私信息、投稿操纵、版权声明、开放许可与参考内容匹配等检查。模型分流、请求示例和使用方法见 [Review-Jev 文档](review-jev/README.md)。

---

## 手机端体验

StudyHub 支持 PWA 安装。通过手机浏览器打开网站，点击右下角的下载箭头即可进入安装流程；iPhone 使用分享菜单中的“添加到主屏幕”，微信等内嵌浏览器可按提示在系统浏览器中打开。

安装后沿用网站的页面、账户和 API。版本化前端资源与离线提示页由 Service Worker 缓存，登录、投稿、文件下载与支付通过在线服务完成；页面更新会在旧窗口关闭后生效。

PWA 图标位于 `frontend/public/icons/`，生成命令为 `node frontend/scripts/build-pwa-icons.mjs`。缓存策略、更新机制和验收说明见 [PWA 技术说明](docs/PWA.md)。

---

## 开源许可

StudyHub 主项目采用 [MIT License](LICENSE)。Review-Jev 的代码许可见 [Apache-2.0 许可证](review-jev/LICENSE)。
