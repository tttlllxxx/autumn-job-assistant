# 秋招助手

面向单个 2027 届求职者的私有秋招工作台，覆盖简历事实库、15 家官方招聘来源、规则/本地向量/LLM 推荐、飞书提醒、事实约束的定制简历、投递记录和版本化备份。

## 最快启动

已安装 Docker Desktop 时，克隆后只需执行：

```bash
git clone https://github.com/tttlllxxx/autumn-job-assistant.git
cd autumn-job-assistant
docker compose up --build
```

首次构建需下载 Python、Chromium 和依赖，耗时会长一些。看到 `Application startup complete` 后打开 <http://localhost:8000>，无需登录。数据默认保存在 Docker 持久卷中；仓库不包含示例简历、岗位库或 API Key。

## 先决条件

- 本机优先使用 Python 3.12、Node.js 22+；也可选用 Docker 与 Docker Compose；
- 至少 4 GB 可用内存；首次构建和首次向量模型下载需要联网；
- 应用按个人本地工具设计，不提供登录页；不要直接暴露到公网。

## 本机启动（优先）

首次安装：

```bash
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
source .venv/bin/activate
playwright install chromium
npm --prefix frontend ci
```

以后在项目根目录一条命令完成前端构建、数据库升级和启动：

```bash
./scripts/start-local.sh
```

默认地址为 <http://127.0.0.1:8000>；可用 `APP_PORT=8010 ./scripts/start-local.sh` 临时修改端口。默认数据写入项目内 `data/`。Docker Compose 会覆盖为容器持久卷路径，不受本地配置影响。

开发前端可运行 `npm run dev`，Vite 会把 `/api` 和 `/health` 代理到 8000 端口。

## Docker 启动

```bash
docker compose up --build
```

默认配置已能用于本机体验，不必创建 `.env`。如需配置端口、LLM 或飞书，再执行 `cp .env.example .env` 并编辑对应项。不要把本工具直接暴露到公网。

浏览器打开 <http://localhost:8000>。应用保持单 worker，内置调度器按 `Asia/Shanghai` 每天 08:00 依次执行采集、推荐和飞书通知；画像尚未确认时只采集。“来源健康”页面可立即手动运行。持久卷分别保存数据库、原始简历、生成简历、备份和模型缓存。

停止但保留数据：

```bash
docker compose down
```

不要使用 `docker compose down -v`，该命令会删除所有持久数据。

## 首次使用闭环

1. 浏览器打开即可使用，应用会自动创建本地会话；无需输入管理员密码。
2. 上传 PDF 或 Markdown；扫描 PDF 会明确提示改用可复制文本文件。
3. 审核事实并确认画像。PII 只在本地文档元数据中保存，不进入脱敏画像或模型输入。
4. 在“来源健康”运行采集，或手工导入官方 URL 和 JD。
5. 运行推荐。LLM 未配置、价格缺失、预算用尽或接口失败时，规则/本地推荐继续工作并标记降级。
6. 人工确认资格待定岗位；只有完整 LLM 重排且总分不低于 80 的新岗位会默认触发飞书。设置页可显式开启降级 Top3 摘要，摘要会明确标注不是完整总分且默认关闭。
7. 在岗位详情确认生成定制简历。任何无有效 `fact_id` 或新增数字、实体、技术/程度的句子都会整句拒绝，失败时不生成 PDF。
8. 直接在投递看板新增机会并维护状态、阶段和结果；修改会即时渲染并自动保存。

## 配置

LLM API 可直接在“设置与备份 → API 配置”中填写；页面保存的 API Key 只保存在本地数据库、不会回显或通过备份导出。环境变量仍可作为默认值：

- `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`：OpenAI-compatible `/chat/completions`；
- `LLM_PROVIDER`：`auto`、`codex`、`api` 或 `disabled`；设置页可随时覆盖。`auto` 在 API 三项齐全时使用 API，否则尝试本机已登录的 Codex CLI；
- `LLM_INPUT_PRICE_RMB_PER_MILLION`、`LLM_OUTPUT_PRICE_RMB_PER_MILLION`：人民币/百万 token；任一缺失即关闭 LLM；
- `LLM_MONTHLY_BUDGET_RMB`：默认 50；
- `CODEX_MODEL`、`CODEX_TIMEOUT_SECONDS`：可选 Codex 模型和超时，默认使用 Codex 当前默认模型与 300 秒。Codex 登录额度无法换算人民币，应用不会伪造成本；
- `FEISHU_WEBHOOK`：个人飞书机器人 Webhook；
- `SCHEDULE_HOUR`：上海时区整点小时，默认 8。

JD 始终作为不可信文本包装，不允许改变系统提示、请求链接或触发工具。

## 历史 CSV 兼容

主界面不再提供 CSV 上传或下载，投递记录统一在看板内部创建和跟踪。为兼容旧数据迁移，后端仍保留 CSV 接口；导入要求 UTF-8（可带 BOM）且严格使用以下列顺序：

```text
公司名,投递渠道,岗位,岗位类型,业务线/部门,链接,Base地,投递日期,状态,当前阶段,阶段结果,当前进度更新时间,内推码,联系人/内推人,面试时间,结果,备注
```

兼容接口首次调用只做 dry-run；有任一非法枚举或日期时不会写入任何记录，验证通过后才能整体提交。未编辑的历史记录导出时保留原始空值和日期字符串。

## 备份与恢复

页面“设置与备份”可创建和下载 ZIP。包内含 `manifest.json`、`data/*.json`、`applications.csv`、原始/生成简历、非秘密设置与 `checksums.sha256`。

恢复顺序为：完整验证格式版本、路径、符号链接、文件数量、压缩前后大小和校验和；临时目录解包；数据库事务导入；最后返回各实体计数。密码哈希、会话、API Key 与飞书 Webhook不会被覆盖。

建议升级前：

```bash
# 先在页面创建并下载备份
docker compose pull
docker compose up --build -d
docker compose exec app alembic current
```

## 测试与验收

```bash
pytest
cd frontend && npm test -- --run && npm run build && cd ..
docker compose config
docker compose up --build -d
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
```

实时来源与 fixture 测试严格分开。安装 Chromium 后执行：

```bash
RUN_LIVE_SOURCES=1 python -m app.cli.live_sources

# 采集后审计重复岗位率（验收阈值 < 1%）
python -m app.cli.duplicate_rate
```

该命令输出 15 家的官方入口、方式、状态、岗位数、字段完整率、验收计入与失败原因，并以退出码 0 表示至少 12 家真实通过。任何需要登录、验证码或风控绕过的来源都会降级，使用控制台手工导入兜底。

推荐精度样本直接来自岗位详情中的“符合/不符合”按钮，不需要维护额外标注文件。达到 50 个不同岗位，且当前 Top10 全部判断后，页面与命令才输出 Precision@10：

```bash
python -m app.cli.evaluate
```

样本不足时退出码为 2，不宣称 Precision@10 达标。

## 排障

- `/health/live` 成功、`/health/ready` 失败：检查数据库卷权限和 `DATABASE_URL`。
- 向量状态降级：确认模型缓存卷可写，联网预热 `BAAI/bge-small-zh-v1.5` 后重算。
- PDF 状态 `pdf_failed`：运行 `playwright install chromium`，容器镜像已内置 Chromium。
- 来源显示降级：查看来源运行记录；不要绕过登录/验证码，改用手工导入。
- LLM 关闭：检查接口三项配置、两项价格和预算页面；采集与本地排序不受影响。

项目源码采用 [MIT License](LICENSE)，第三方依赖说明见 `THIRD_PARTY_NOTICES.md`。PyMuPDF 为 AGPL；若未来公开提供网络服务或闭源分发，请先完成许可证评估。
