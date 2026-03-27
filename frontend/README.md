# studyhub frontend

前端位于 `frontend/`，基于 Next.js。它需要同时适配 `local-dev`、`preview` 和 `production` 三类环境，并且不依赖仓库外的绝对路径。

## 推荐开发方式

优先从仓库根目录启动整套本地开发环境：

```bash
bash scripts/dev/docker-dev-up.sh
```

默认地址：

- frontend：`http://127.0.0.1:3100`
- backend API：`http://127.0.0.1:8111/api`

## local-dev 下的前端体验

当前前端已经对 `local-dev` 做了几项开发友好处理：

- 登录页提供开发账号的快捷入口
- 页面会显示明确的环境标识，避免误认成 preview 或 production
- mock 场景下的外链图片会自动映射到本地占位图，避免页面因为示例域名失效而崩溃

这样做的目标是：既保留真实应用的登录流程，又不让开源协作者把时间浪费在无关的环境问题上。

## 什么时候用 Docker，什么时候手动跑前端

- 如果你在做正常功能开发，或者需要和后端联调，优先使用 `docker compose local-dev`
- 如果你只是想快速看页面、改样式或临时检查某个 UI，手动启动前端会更轻

两者最大的区别不在前端本身，而在后端和依赖环境：

- Docker local-dev 更接近真实开发环境
- 手动方式更轻，但通常更偏演示和局部调试

## 手动启动

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8011/api npm run dev
```

## 构建

```bash
cd frontend
npm run build
npm start
```
