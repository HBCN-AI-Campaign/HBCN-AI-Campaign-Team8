# 境外贷款单据智能审核平台 —— React 前端（迁移中）

这是从 Vue 3 版本（`../frontend`）迁移而来的 React 重构骨架。

## 技术栈

| 维度 | Vue 版 | React 版（本项目） |
|------|--------|--------------------|
| 框架 | Vue 3 (`<script setup>`) | React 18 |
| 路由 | vue-router | react-router-dom v6 |
| 状态 | Pinia | zustand |
| UI 库 | Element Plus | Ant Design v5 |
| HTTP | axios | axios（原样复用） |
| 构建 | Vite | Vite |
| 语言 | TypeScript | TypeScript |

## 启动

```bash
npm install
npm run dev     # 默认端口 5174（Vue 版占用 5173）
```

后端 FastAPI 仍跑在 `127.0.0.1:8000`，`/api` `/pdf` `/uploads` 由 Vite 代理转发。

## 迁移进度

- [x] 项目脚手架（Vite + React + TS）
- [x] 可复用层：`types.ts` / `utils.ts` / `styles.css`
- [x] 鉴权状态：`stores/auth.ts`（zustand）
- [x] API 层：`api.ts`（解耦 Vue 生态，拦截器改用 zustand + antd message）
- [x] 路由 + 鉴权守卫：`router/`（ProtectedRoute 替代 beforeEach）
- [x] 布局骨架：`layouts/MainLayout.tsx`
- [x] 登录页：`views/LoginView.tsx`（**完整可用**）
- [ ] 工作台：`views/DashboardView.tsx`（占位，待迁移）
- [ ] 发起任务：`views/CreateTaskView.tsx`（占位，待迁移）
- [ ] 任务详情：`views/TaskObjectView.tsx`（占位，核心复杂页，待迁移）
- [ ] PDF 查看器：`components/PdfSourceViewer`（待迁移）

## 目录结构

```
src/
  api.ts                 # axios 封装 + 拦截器（可注入导航回调）
  types.ts               # TS 类型（100% 复用自 Vue 版）
  utils.ts               # 纯函数 + 字典（tag 类型已适配 antd）
  styles.css             # 全局 CSS 变量
  main.tsx / App.tsx     # 入口 + antd ConfigProvider(zhCN)
  stores/auth.ts         # zustand 鉴权 store
  router/
    index.tsx            # createBrowserRouter 路由表
    ProtectedRoute.tsx   # 鉴权/角色守卫
  layouts/MainLayout.tsx # 顶栏 + Outlet
  views/                 # 四个页面
```
