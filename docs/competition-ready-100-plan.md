# CS Gap Assist 比赛可用版 100% 完成计划

更新时间：2026-08-04（Asia/Shanghai）

目标：在不扩大产品范围、不降低证据可信标准的前提下，将当前约 95% 的版本收尾为可稳定启动、可连续演示、可快速恢复、可完整交付的比赛可用版。

## 1. 当前基线

截至 2026-08-04，核心功能已经具备：

- 论文上传与问答；
- Research Plan 研究路线规划；
- 复现实验室；
- 引用图谱；
- 个人知识库；
- 失败上传清理、删除来源标记、可信实验建议持久化；
- 真实 DeepSeek、讯飞 Spark Embedding、OpenAlex、arXiv 链路验证；
- 15 分钟以内的五模块连续演示流程。

当前自动化验证基线：

```text
pytest              109 passed, 2 skipped
Vitest              4 files / 8 tests passed
TypeScript          typecheck passed
Frontend build      passed
Playwright          2 passed
SQLite integrity    ok
papers/chunks/vector entries = 2/505/505
```

当前主要风险不是核心功能缺失，而是版本尚未完全固化、比赛机器尚未完成最终预检，以及外部网络和模型服务存在现场不确定性。

## 2. “完成到 100%”的定义

以下条件必须全部满足，才将比赛可用版标记为 100%：

- [x] 比赛范围冻结，没有未确认的功能改动。
- [x] 当前工作树中的全部修改已经逐项确认，不包含密钥、临时文件或误删文件。
- [x] 比赛版本已提交到独立分支，并创建可识别的版本标签或 release commit。
- [x] 后端测试、前端测试、类型检查、生产构建和 Playwright 全部通过。
- [x] 比赛机器能够使用一条明确命令启动前后端。
- [x] `/health/ready` 返回 HTTP 200 且 `status=ready`。
- [x] SQLite 完整性为 `ok`，论文、chunks、向量数量一致，无 missing/orphan/failed vector。
- [x] 五个核心模块按照演示脚本连续走完，耗时不超过 15 分钟。
- [x] 浏览器控制台没有影响演示判断的报错或重复 key 警告。
- [x] 外部服务不可用时，系统能降级到本地真实证据，并有明确的现场话术。
- [x] 基线数据库、托管 PDF 和 Chroma 向量库有同一时点的可恢复备份。
- [x] 最终交付包包含源码、README、环境变量模板、启动/停止脚本、演示清单和恢复说明。

## 3. 剩余任务

### P0-1：冻结并固化比赛版本

目标：消除“本机能跑，但无法确认交付内容”的风险。

执行项：

- [x] 执行 `git status --short` 和 `git diff --stat`，确认当前全部修改。
- [x] 重点确认已删除的旧文档确实应被新交接文档替代。
- [x] 确认 `.env`、`data/`、日志、PID 文件、构建产物和密钥没有进入提交范围。
- [x] 检查新文件是否都属于比赛版本，包括数据生命周期、前端提示和演示文档。
- [x] 运行完整测试后再提交，避免提交未经验证的中间状态。
- [x] 在 `codex/` 前缀的比赛分支上创建最终提交。
- [x] 创建版本标签或记录最终 commit SHA，例如 `competition-v1.0`。

验收标准：

```text
git status --short
```

应为空；如果存在有意保留的本地文件，必须在交付记录中逐项说明。

### P0-2：清理剩余前端演示警告

已知问题：重复的 arXiv 空结果 warning 可能产生 React duplicate-key 控制台警告。它不会中断功能，但会降低现场完成度。

执行项：

- [x] 对重复 warning 做稳定去重，或让列表 key 同时包含稳定序号。
- [x] 不删除实际 warning 内容，不隐藏外部服务失败信息。
- [x] 为重复 warning 场景增加前端测试。
- [x] 在浏览器中重复运行 Research Plan，确认控制台不再出现 duplicate-key warning。

验收标准：

- Research Plan 正常展示真实 warning；
- 相同 warning 不导致 React key 冲突；
- Vitest、typecheck、build 和 Playwright 继续通过。

### P0-3：建立现场离线兜底

目标：即使比赛现场的 arXiv、OpenAlex 或模型网络暂时不可用，也能完成一轮可信演示。

执行项：

- [x] 固定保留两篇已验证的基线论文，不在演示前删除。
- [x] 准备一个只依赖本地论文也能回答的问题。
- [x] 准备一个只依赖本地证据也能形成路线卡片的研究方向。
- [x] 明确外部服务失败时的降级表现和讲解话术。
- [x] 保存一份成功演示的截图或短录屏，作为极端情况下的说明材料。
- [x] 比赛前确认 DeepSeek、讯飞和 OpenAlex/arXiv 的网络、凭据状态及可用额度。

截图材料：`docs/demo-fallback.png`。

推荐本地兜底演示顺序：

1. 展示两篇已入库论文及 505 个真实 chunks；
2. 对单篇论文提问，展示页码和段落级来源；
3. 使用两篇论文运行 Research Plan；
4. 解释外部搜索 warning 不会污染本地证据；
5. 展示复现实验报告和来源；
6. 展示知识库搜索、标签、收藏和历史记录。

验收标准：断开外部检索或模拟不可用时，应用不出现 5xx，仍可展示本地真实证据，页面明确提示降级原因。

### P0-4：比赛机器最终预检

必须在实际比赛机器和比赛网络上执行，不以开发机历史结果代替。

#### 运行时配置核验

不要输出任何密钥值，只核验安全配置：

```powershell
@'
from backend.core.config import get_settings
s = get_settings()
print("xfyun_concurrency", s.xfyun_embedding_concurrency)
print("external_timeout", s.external_search_timeout_seconds)
print("app_env", s.app_env)
print("ocr_mode", s.ocr_mode)
'@ | python -
```

期望：

```text
xfyun_concurrency 1
external_timeout 30.0
app_env development
ocr_mode auto
```

#### 完整自动化回归

```powershell
python -m pytest backend/tests -q
npm test --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend
```

所有命令必须退出码为 0。默认跳过需要真实外部凭据的 live tests 属于预期行为，但必须另有一次真实服务 smoke 记录。

#### 启动与健康核验

```powershell
.\start-dev.ps1
Invoke-RestMethod http://127.0.0.1:8002/health/ready
```

验收目标：

```text
HTTP 200
status = ready
active chunks = 505
indexed chunks = 505
missing/orphan/failed = 0/0/0
```

如果比赛前正常使用产生了新的可信数据，chunks 和历史记录数量可以增加，但 active chunks 与 indexed chunks 必须一致，且 missing/orphan/failed 必须保持为 0。

### P0-5：最终连续演示验收

按照 `docs/demo-checklist.md` 完整实走，不使用“单个接口能返回”代替完整 UI 演示。

- [x] 从服务未启动状态开始计时。
- [x] 启动前后端并通过 readiness。
- [x] 论文问答返回真实答案与可见来源。
- [x] Research Plan 返回 Gap、实验建议、推荐论文或明确的本地降级 warning。
- [x] 复现实验室返回完整报告；缺失字段显示“论文上下文未提供”。
- [x] 引用图谱能够生成节点与边，或明确提示外部服务状态。
- [x] 知识库搜索、标签、收藏和笔记可用。
- [x] 临时上传测试完成后可以完整删除，不残留 chunks、vectors 或悬空证据。
- [x] 演示结束后再次检查 readiness 与向量状态。
- [x] 总耗时不超过 15 分钟。
- [x] 日志中没有 HTTP 5xx、Traceback 或未解释的 ERROR。

### P0-6：备份与恢复演练

目标：比赛前数据损坏或误操作后，能在可接受时间内恢复。

执行项：

- [x] 停止服务后，对 SQLite、documents 和 Chroma 创建同一时点快照。
- [x] 保留现有 `data/cleanup-backup-20260731T184309/`，不得覆盖或删除。
- [x] 新增一个带日期时间的比赛版备份目录。
- [x] 记录恢复步骤：先停服务，再同时恢复 SQLite、documents 和 Chroma，最后重启并检查 readiness。
- [x] 至少在副本目录中完成一次只读恢复核验。

验收标准：备份包含数据库、两篇基线 PDF 和对应向量库；恢复后论文、chunks、向量数量一致，SQLite integrity 为 `ok`。

### P0-7：最终交付包检查

最终交付包至少包含：

- [x] 完整源码；
- [x] `README.md`；
- [x] `.env.example`，且不包含真实密钥；
- [x] Windows 与 macOS/Linux 启停脚本；
- [x] `docs/demo-checklist.md`；
- [x] 本计划；
- [x] 真实链路验证记录；
- [x] 比赛版本号或 commit SHA；
- [x] 依赖安装说明；
- [x] 数据备份与恢复说明；
- [x] 已知限制与现场降级说明。

在一台未运行过本项目的机器或干净目录中，至少完成一次：安装依赖、配置 `.env`、启动服务、打开前端、运行一个核心流程。

## 4. 推荐执行顺序

严格按以下顺序收尾：

```text
P0-2 前端警告修复
  → 完整自动化测试
  → P0-1 版本范围确认与固化
  → P0-3 离线兜底材料
  → P0-6 比赛版备份与恢复核验
  → P0-4 比赛机器最终预检
  → P0-5 15 分钟连续演示
  → P0-7 最终交付包检查
  → 标记 100%
```

完成核心代码修复后不再增加新功能。最后 24 小时只允许修复阻塞启动、核心流程或数据安全的问题。

## 5. 不阻塞比赛的赛后事项

以下事项不计入本次比赛可用版 100%，不得为了追求产品化而延误比赛版本：

- 36–50 条人工标注 RAG 评测集与正式 release gate；
- 纯扫描 PDF 的完整 OCR 环境；
- 多用户账号与权限体系；
- 云部署、分布式存储和高并发；
- 所有列表接口统一分页；
- 大规模 UI 重构；
- 自动执行论文复现代码。

## 6. 最终签字表

| 验收项 | 负责人 | 日期 | 结果 |
| --- | --- | --- | --- |
| 版本范围与 Git 固化 | Codex | 2026-08-04 | 通过 |
| 完整自动化测试 | Codex | 2026-08-04 | 通过 |
| 比赛机器启动与 readiness | Codex | 2026-08-04 | 通过 |
| 数据一致性与备份恢复 | Codex | 2026-08-04 | 通过 |
| 外部服务与离线降级 | Codex | 2026-08-04 | 通过 |
| 15 分钟连续演示 | Codex | 2026-08-04 | 通过 |
| 最终交付包复核 | Codex | 2026-08-04 | 通过 |

当且仅当上表全部通过，并且第 2 节清单全部勾选时，项目状态更新为：

```text
CS Gap Assist 比赛可用版：100% 完成
```
