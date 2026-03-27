# StudyHub

![StudyHub 海报](assets/studyhub-poster.png)

StudyHub 是一个面向高校场景的知识共享与校园互助平台，支持资料共享、经验分享、求购协作与校园集市等能力。这个仓库是面向开源协作整理后的 FastAPI + Next.js 版本。

## 仓库结构

- `backend/`：FastAPI 后端、测试、fixtures 与运维辅助代码
- `frontend/`：Next.js 前端
- `scripts/`：开发、部署、worker 与数据库操作脚本
- `docs/`：本地工作文档，默认不进入公开仓库
- `private/`：preview / production 私密配置与运行资产，默认不进入公开仓库

## 开发入口

- 推荐开发：`bash scripts/dev/docker-dev-up.sh`
- 轻量启动：`bash scripts/dev/local-dev-up.sh`

具体说明见：

- [backend/README.md](backend/README.md)
- [frontend/README.md](frontend/README.md)
- [scripts/README.md](scripts/README.md)

## 相关仓库

- Spring Boot 基线仓库：`https://github.com/ChengjinLii/studyhub-springboot`
