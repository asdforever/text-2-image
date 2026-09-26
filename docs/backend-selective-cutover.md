# 当前 API 路由与启动方式

2026-09-21 起，本项目取消旧 Node API 选择性切流。前端全部 `/api` 请求统一代理到 FastAPI，不再保留旧服务兜底。

## 开发环境

- 前端：`npm run dev`，默认 5173。
- 后端：`npm run api`，同时启动 8000 上的 FastAPI 和批次 Worker。
- `VITE_FASTAPI_PROXY_TARGET` 可在根 `.env` 或启动环境中设置，默认 `http://127.0.0.1:8000`。
- Node.js 用于前端构建和 Vite 开发服务，不需要另外启动 Node API。

未知 API 由 FastAPI 返回 404，不能通过启动旧服务补齐。主图、详情、画布和图片编辑使用当前项目接口；未挂载的旧规划、旧风格库界面和旧客户端方法已移除。

## 白底图库

“从已有库选择”读取当前 `/api/asset-libraries`、`/api/product-libraries`、`/api/test-product-libraries`。素材和测试产物必须显式标记为白底图，正式成品只显示已发布白底图版本。普通图片不会被自动视为白底图。

各来源及其下属库、成品独立处理读取失败，成功结果继续显示；窗口保留错误提示与重新加载按钮。选择图片后仍通过项目上传接口保存来源信息。

## 验证

```powershell
npx tsx --test tests/vite-proxy-routing.test.ts
npx playwright test tests/e2e/white-background-library.spec.ts
Invoke-RestMethod http://127.0.0.1:5173/api/health
Invoke-RestMethod http://127.0.0.1:5173/api/ready
Invoke-RestMethod http://127.0.0.1:5173/api/test-product-libraries
```

生产环境的静态文件服务应将 `/api` 转发到后端 API，Vite 的开发代理不会写入构建产物。前后端可以独立部署，Worker 与 API 使用同一数据库和对象存储。

本文替代历史上的 Node/FastAPI 并行切流操作说明；历史 OpenSpec 记录仅用于追溯。
