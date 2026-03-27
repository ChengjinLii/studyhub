# StudyHub Frontend

StudyHub 的 Next.js 前端，目录已经从旧的 `apps/web` 收敛到顶层 `frontend/`。

## 推荐开发方式

优先配合仓库根目录的 `docker compose`：

```bash
cd /root/StudyHub-FastAPI
bash scripts/docker-dev-up.sh
```

此时前端地址：

- `http://127.0.0.1:3100`

后端 API 默认会指向：

- `http://127.0.0.1:8111/api`

配合 `local-dev` 使用时：

- 登录页会显示 `Local Dev` 快捷入口
- 可以直接进入预置账号 `developer`
- 页面左下角会显示 `Local Dev` 环境标识
- 示例外链资源会自动映射到本地占位图，避免 mock 域名导致页面崩溃

## 开发方式选择

- 如果你要参与这个项目的正常开发，优先使用根目录的 `docker compose`
- 如果你只是想快速打开前端页面看看，或者临时改 UI，可以手动本地运行
- 两者最大的区别不在前端本身，而在后端和依赖环境：`docker compose` 更接近真实开发环境，shell 方式更轻但更偏演示/调试

## 手动开发

如果不用 Docker：

```bash
cd /root/StudyHub-FastAPI/frontend
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8011/api npm run dev
```

## 构建

```bash
cd /root/StudyHub-FastAPI/frontend
npm run build
npm start
```
