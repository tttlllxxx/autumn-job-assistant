# 第三方软件声明

本项目仅使用下表所列的直接依赖。版本与 `pyproject.toml`、`frontend/package.json` 保持一致；传递依赖的许可证可通过 `pip-licenses` 和 `npm license-checker` 在构建环境中复核。

| 名称 | 版本 | 用途 | 许可证 |
|---|---:|---|---|
| FastAPI | 0.116.1 | Web API | MIT |
| Uvicorn | 0.35.0 | ASGI 服务 | BSD-3-Clause |
| Pydantic / pydantic-settings | 2.11.7 / 2.10.1 | 数据与配置校验 | MIT |
| SQLAlchemy | 2.0.43 | ORM | MIT |
| Alembic | 1.16.5 | 数据库迁移 | MIT |
| APScheduler | 3.11.0 | 定时任务 | MIT |
| HTTPX | 0.28.1 | HTTP 客户端 | BSD-3-Clause |
| Beautiful Soup | 4.13.5 | HTML 解析 | MIT |
| lxml | 6.0.1 | HTML/XML 解析 | BSD-3-Clause |
| Playwright Python | 1.55.0 | 动态页面与 PDF | Apache-2.0 |
| PyMuPDF | 1.26.4 | PDF 文本解析 | AGPL-3.0-or-later |
| sentence-transformers | 5.1.0 | 本地语义召回 | Apache-2.0 |
| argon2-cffi | 25.1.0 | 密码哈希 | MIT |
| python-multipart | 0.0.20 | 表单与文件上传解析 | Apache-2.0 |
| setuptools / wheel | >=75 / 构建环境版本 | Python 包构建 | MIT |
| Pytest | 8.4.1 | 后端自动测试 | MIT |
| pytest-asyncio | 1.1.0 | 异步测试 | Apache-2.0 |
| pytest-cov | 6.2.1 | 测试覆盖率支持 | MIT |
| React / React DOM | 19.1.1 | 前端界面 | MIT |
| React Router | 7.8.2 | 前端路由 | MIT |
| TanStack Query | 5.87.1 | 服务端状态 | MIT |
| Zod | 4.1.5 | 前端数据校验 | MIT |
| Vite | 7.1.3 | 前端构建 | MIT |
| TypeScript | 5.9.2 | 类型检查 | Apache-2.0 |
| @types/node | 24.3.0 | Vite/TypeScript Node.js 类型声明 | MIT |
| Vitest | 3.2.4 | 前端测试 | MIT |
| @vitejs/plugin-react | 5.0.2 | React/Vite 编译插件 | MIT |
| @testing-library/react / jest-dom | 16.3.0 / 6.8.0 | 前端组件测试 | MIT |
| jsdom | 26.1.0 | 前端测试 DOM 环境 | MIT |
| @types/react / @types/react-dom | 19.1.12 / 19.1.9 | React TypeScript 类型声明 | MIT |

注意：PyMuPDF 使用 AGPL 许可证。本项目按提示词作为个人私有项目交付；若未来以网络服务向第三方提供或进行闭源分发，应先完成许可证法律评估，或替换为许可证更宽松的 PDF 解析器。
