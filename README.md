# StudyHub

StudyHub 是一个面向高校场景的知识共享与校园互助平台，支持资料共享、经验分享、求购协作与校园集市等能力。官网网址：https://study-hub.cn/

![StudyHub 海报](assets/studyhub-poster.png)

## 仓库结构

- `backend/`：FastAPI 后端、测试、fixtures 与运维辅助代码
- `frontend/`：Next.js 前端
- `scripts/`：开发、部署、worker 与数据库操作脚本

## 开发入口

- 推荐开发：`bash scripts/dev/docker-dev-up.sh`
- 轻量启动：`bash scripts/dev/local-dev-up.sh`

具体说明见：

- [backend/README.md](backend/README.md)
- [frontend/README.md](frontend/README.md)
- [scripts/README.md](scripts/README.md)

## 相关仓库

- SpringBoot 版本：`https://github.com/ChengjinLii/studyhub-springboot`（暂未开源）
