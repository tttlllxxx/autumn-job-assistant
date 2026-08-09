# 秋招助手

一个无需登录、在本地直接使用的个人秋招工作台。它把简历画像、官方岗位采集、岗位推荐、简历修改建议和投递跟踪放在同一个界面中，数据默认只保存在当前设备。

## 快速开始

### 使用 Docker（最省事）

先安装 Docker Desktop，然后运行：

```bash
git clone https://github.com/tttlllxxx/autumn-job-assistant.git
cd autumn-job-assistant
docker compose up --build
```

首次构建需要下载 Python、Chromium、前端依赖和向量模型，耗时会长一些。看到 `Application startup complete` 后打开 <http://localhost:8000>。

无需注册或输入管理员密码。默认配置可以直接体验简历解析、岗位采集、本地推荐和投递看板；使用 LLM 前再到页面中配置 Codex 或 API。

停止服务但保留数据：

```bash
docker compose down
```

> 不要运行 `docker compose down -v`，它会删除数据库、简历、备份和模型缓存。

### 本机启动

适合希望使用本机 Codex 登录态，或需要调试代码的用户。建议使用 Python 3.12、Node.js 22+，并预留至少 4 GB 内存。

首次安装：

```bash
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
source .venv/bin/activate
playwright install chromium
npm --prefix frontend ci
```

以后在项目根目录执行：

```bash
./scripts/start-local.sh
```

打开 <http://127.0.0.1:8000>。如需修改端口：

```bash
APP_PORT=8010 ./scripts/start-local.sh
```

## 第一次使用

建议按下面的顺序完成一次完整流程：

1. 打开“简历导入”，上传可复制文本的 PDF 或 UTF-8 Markdown，文件不能超过 10 MB。
2. 打开“画像与事实”，逐条检查解析结果并确认画像。后续推荐和修改建议都以这里确认的事实为准。
3. 打开“数据来源”，先运行内置官方来源，也可以添加其他公司的官方招聘入口。
4. 打开“岗位推荐”，点击“更新推荐”，查看推荐、待确认和已过滤岗位。
5. 点进岗位详情，判断“符合”或“不符合”。这些反馈会自动成为推荐精度样本，不需要额外上传标注文件。
6. 对感兴趣的岗位点击“生成修改建议”，然后在“修改建议”中查看修改前后对照和理由。
7. 在“投递看板”中新增机会，持续更新投递状态、面试阶段和结果。
8. 在“设置与备份”创建 ZIP 备份，尤其建议在升级或恢复数据前备份。

## 页面使用说明

| 页面 | 用途 | 常用操作 |
| --- | --- | --- |
| 01 概览 | 查看画像、岗位、推荐和投递概况 | 检查待处理事项 |
| 02 岗位推荐 | 按综合匹配度浏览岗位 | 更新推荐、切换状态、进入岗位详情 |
| 03 投递看板 | 在应用内部实时跟踪求职进度 | 新增机会、修改阶段和结果 |
| 04 简历导入 | 导入原始简历 | 上传 PDF 或 Markdown、查看解析状态 |
| 05 画像与事实 | 审核推荐所依据的个人事实 | 修改并确认技能、教育和项目经历 |
| 06 修改建议 | 汇总主动生成的岗位专属建议 | 查看修改前后示例、理由和能力缺口 |
| 07 数据来源 | 管理和运行招聘来源 | 全部采集、单独运行、添加公司、手工录入 JD |
| 08 设置与备份 | 配置 LLM、预算、通知和数据 | 选择提供方、管理 Key、备份和恢复 |

### 简历与画像

- 支持可复制文本的 PDF、`.md` 和 `.markdown`；扫描版 PDF 无法可靠解析时会给出提示。
- 画像确认前可以反复修改事实。完整的项目或经历应作为一条事实保留，避免拆成失去上下文的片段。
- 姓名、联系方式等个人信息仅用于本地文档处理，不进入脱敏画像或模型输入。
- 修改建议只能基于已确认事实。模型新增的数字、实体、技术或经历程度会被拒绝。

### 数据来源与岗位采集

“数据来源”提供三种录入方式：

1. **内置来源**：点击“立即采集全部”，或对单家公司点击“单独运行”。
2. **添加公司来源**：填写公司名称和 HTTPS 官方招聘入口，系统会立即解析，并在之后的每日任务中继续更新。
3. **手工录入官方 JD**：当页面需要登录、验证码或自动采集失败时，粘贴官方岗位链接和完整 JD。

自定义来源被移除后不会再自动更新，但已经采集的历史岗位仍会保留。系统不会绕过登录、验证码或网站风控。

### 岗位推荐与反馈

- “推荐”显示通过硬条件的岗位；“待确认”表示招聘类型或毕业年份等信息仍需人工确认；“已过滤”会显示未通过原因。
- 综合匹配由规则、本地向量和可选 LLM 重排组成。未配置 LLM、预算用尽或接口失败时，规则和本地推荐仍可工作，并在页面标明降级状态。
- 岗位详情中的匹配说明直接显示可读的简历事实，不显示内部 `fact_id`。
- 每个岗位的“符合/不符合”选择会自动积累精度样本。至少判断 50 个不同岗位，且当前 Top 10 全部完成判断后，设置页才会显示 Precision@10。
- 只有主动点击“生成修改建议”的岗位才会出现在“修改建议”页面。

### 投递看板

投递记录直接在看板内创建和维护，不需要上传外部表格。修改状态、当前阶段、面试时间或结果后，页面会即时刷新并自动保存。

## 配置 LLM

不配置 LLM 也能使用岗位采集、规则筛选、本地向量排序和投递看板。需要更细的岗位重排或简历修改建议时，打开“设置与备份 → 模型、预算与数据”。

### 使用 Codex

1. 先在本机终端完成 Codex 登录，并确认 `codex` 命令可用。
2. 在“模型提供方”选择“Codex 本地登录”或“自动选择”。
3. 使用 `./scripts/start-local.sh` 启动应用。

Codex 方式依赖宿主机的登录态，推荐配合本机启动使用。Docker 容器默认不会继承宿主机 Codex 登录态；Docker 用户更适合配置 API。

### 使用 OpenAI-compatible API

1. 在“API 配置”中点击“编辑 API 配置”。
2. 填写 API Base URL，例如 `https://api.openai.com/v1`，不要包含末尾的 `/chat/completions`。
3. 填写模型名称、每百万 token 的输入/输出人民币价格和月度预算。已收录模型会给出官方参考价格，未知模型需按供应商账单填写。
4. 在“密钥列表”新增一个或多个 API Key，并通过页面上方选择器指定当前 Key。
5. 保存后将“模型提供方”切换为“OpenAI-compatible API”或“自动选择”。

API Key 只保存在本地数据库，不会在页面中回显原文，也不会写入备份。环境变量配置会作为只读选项出现在密钥列表中。

也可以复制环境变量模板后配置：

```bash
cp .env.example .env
```

常用变量：

| 变量 | 说明 |
| --- | --- |
| `APP_PORT` | 对外端口，默认 `8000` |
| `LLM_PROVIDER` | `auto`、`codex`、`api` 或 `disabled` |
| `LLM_BASE_URL` | OpenAI-compatible API 根地址 |
| `LLM_API_KEY` | API Key |
| `LLM_MODEL` | 模型名称 |
| `LLM_INPUT_PRICE_RMB_PER_MILLION` | 每百万输入 token 的人民币价格 |
| `LLM_OUTPUT_PRICE_RMB_PER_MILLION` | 每百万输出 token 的人民币价格 |
| `LLM_MONTHLY_BUDGET_RMB` | 月度预算，默认 `50` |
| `FEISHU_WEBHOOK` | 可选的个人飞书机器人 Webhook |
| `SCHEDULE_HOUR` | 每日任务执行小时，默认上海时区 `8` 点 |

## 自动任务与飞书通知

应用按 `Asia/Shanghai` 时区每天 08:00 依次执行采集、推荐和飞书通知；可通过 `SCHEDULE_HOUR` 修改整点小时。画像尚未确认时只执行采集。

只有完整 LLM 重排且总分不低于 80 的新岗位会默认触发飞书。可以在设置页开启“降级 Top3 摘要”，但该选项默认关闭，消息会明确标注不是完整 LLM 总分。

## 数据、备份与升级

### 数据保存位置

- 本机启动：数据保存在项目的 `data/` 目录。
- Docker 启动：数据库、原始简历、生成内容、备份和模型缓存分别保存在 Docker 持久卷中。
- 仓库的 `.gitignore` 已排除 `.env`、数据库、简历、备份、模型和构建产物。

应用按个人本地工具设计，没有登录页。请只在可信设备上运行，不要直接暴露到公网。

### 创建和恢复备份

在“设置与备份”点击“创建版本化 ZIP”并下载。备份包含业务数据和简历文件，但不包含密码、会话、API Key 或飞书 Webhook。

恢复会替换画像、岗位、推荐、投递和简历版本；当前密钥保持不变。执行前请确认选择了正确的 ZIP，并保留一份当前备份。

### 更新项目

先在页面创建并下载备份，再执行：

```bash
git pull
docker compose up --build -d
docker compose exec app alembic current
```

本机启动用户更新依赖后重新运行：

```bash
source .venv/bin/activate
uv pip install --python .venv/bin/python -e '.[dev]'
npm --prefix frontend ci
./scripts/start-local.sh
```

## 常见问题

### 页面打不开

- Docker：运行 `docker compose ps` 和 `docker compose logs app`，确认容器仍在运行。
- 本机：确认终端中出现 `Application startup complete`，并检查端口是否已被占用。
- 健康检查：访问 <http://localhost:8000/health/live> 和 <http://localhost:8000/health/ready>。

### LLM 显示关闭或降级

检查模型提供方、API 地址、模型名称、当前 API Key、输入/输出价格和剩余预算。接口失败不会阻止岗位采集和本地排序。

### 来源没有采集到岗位

查看来源卡片上的最近错误并尝试“单独运行”。如果站点要求登录、验证码或解析仍失败，使用“手工录入官方 JD”。

### 简历 PDF 解析失败

确认 PDF 中的文字可以选中复制。扫描件请先转成可复制文本，或改用 UTF-8 Markdown。本机缺少浏览器时执行 `playwright install chromium`。

### 向量功能降级

确认首次运行时网络可用，并确保 `data/models/` 或 Docker 模型缓存卷可写。模型为 `BAAI/bge-small-zh-v1.5`。

## 开发与验收

启动前端开发服务器：

```bash
npm --prefix frontend run dev
```

运行测试和生产构建：

```bash
pytest
npm --prefix frontend test -- --run
npm --prefix frontend run build
docker compose config
```

安装 Chromium 后可运行实时来源验收和重复岗位审计：

```bash
RUN_LIVE_SOURCES=1 python -m app.cli.live_sources
python -m app.cli.duplicate_rate
python -m app.cli.evaluate
```

实时来源测试不会绕过登录、验证码或风控。`evaluate` 在样本不足时退出码为 2，不会宣称精度达标。

## 历史 CSV 迁移

当前界面不提供 CSV 上传或下载，投递记录统一在看板内部管理。后端仍保留旧版 CSV 迁移接口；导入要求 UTF-8（可带 BOM）并严格使用以下列顺序：

```text
公司名,投递渠道,岗位,岗位类型,业务线/部门,链接,Base地,投递日期,状态,当前阶段,阶段结果,当前进度更新时间,内推码,联系人/内推人,面试时间,结果,备注
```

项目源码采用 [MIT License](LICENSE)，第三方依赖说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。PyMuPDF 使用 AGPL；公开提供网络服务或闭源分发前请先完成许可证评估。
