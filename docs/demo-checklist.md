# CS Gap Assist 演示预检清单

适用版本：比赛可用版  
预计用时：12–15 分钟  
基线：2 篇保留论文、505 个 chunks、505 个 ready vectors

## 1. 启动与健康检查（1 分钟）

在仓库根目录执行：

```powershell
.\stop-dev.ps1
.\start-dev.ps1 -NoOpen
Invoke-RestMethod http://127.0.0.1:8002/health/ready
```

确认：

- HTTP 200 且顶层 `status=ready`。
- `sqlite`、`documents`、`vector_index`、`embedding_config`、`api_auth`、`ingestion_worker` 均为 `ready`。
- `vector_index.missing_chunk_count=0`、`orphan_vector_count=0`。
- OCR 在未安装 Pillow/pytesseract 时显示 `unavailable` 属于已知可接受状态；演示只使用可提取文本的 PDF。
- 实际配置为 `XFYUN_EMBEDDING_CONCURRENCY=1`、`EXTERNAL_SEARCH_TIMEOUT_SECONDS=30`；不得打印 `.env` 或任何密钥。

## 2. 数据基线（30 秒）

只读检查：

```powershell
py -3.11 -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('select count(*) from papers').fetchone()[0], c.execute('select count(*) from chunks').fetchone()[0], c.execute('select count(*) from vector_index_entries where status=''ready''').fetchone()[0])"
```

期望：`2 505 505`。若演示者或用户刚新增了数据，先确认新增来源，不得为追求数字而删除未知数据。

两篇基线论文：

- `1_VRD_Language_Priors_Lu2016.pdf`
- `2_Neural_Motifs_Zellers2018.pdf`

## 3. 五模块演示路径（约 10–12 分钟）

### 3.1 论文问答（2 分钟）

1. 打开 `http://localhost:5173/`，进入“论文问答”。
2. 选择 `1_VRD_Language_Priors_Lu2016.pdf`。
3. 提问：“这篇论文使用了哪些数据集和评价指标？请仅依据论文回答并带页码引用。”
4. 确认回答包含来源编号，来源卡显示页码和 chunk；无可靠来源时应 fail-closed，而不是编造答案。

讲解重点：回答、页码、chunk 三者可追溯；论文内容被视为不可信材料，不能改变系统指令。

### 3.2 研究路线（3 分钟）

1. 进入“研究路线”，选中两篇基线论文。
2. 研究方向填写：“视觉关系检测在跨域场景中的鲁棒性评估与改进”。
3. 运行 Agent，展示工具步骤、Research Gap、实验建议和课题执行卡。
4. 检查推荐论文：有 arXiv 结果时显示真实链接；无结果时显示 warning，并继续使用本地真实证据。

讲解重点：Agent 有最大步数与单 Gap 失败隔离；可信实验建议会进入实验历史。

### 3.3 复现实验室（2 分钟）

1. 进入“复现实验室”，选择一篇基线论文和“标准复现”。
2. 需求填写：“整理数据集、指标、Baseline、复现步骤和风险，不运行代码。”
3. 运行后展示工具轨迹、结构化报告、代码/仿真模板和 non-claims。
4. 缺失字段应显示“论文上下文未提供”；系统最多修复一次，仍缺失就保留 unknown 语义。

讲解重点：这是辅助复现，不自动运行代码、不承诺论文指标、不补造论文未提供的信息。

### 3.4 引用图谱（1–2 分钟）

1. 进入“引用图谱”，选择一篇基线论文并加载图谱。
2. 展示节点、连线和关键论文标记。
3. OpenAlex 返回空图时，明确说明这是 fail-closed 设计，不会用伪造节点填充。

讲解重点：图谱来自真实 OpenAlex 或本地可验证关系；空结果不是应用崩溃。

### 3.5 知识库与安全删除（2–3 分钟）

1. 进入“知识库”，展示标签、收藏、笔记和跨库搜索。
2. 只上传一篇临时、纯文本、非敏感 PDF；等待状态 ready。
3. 不用临时论文生成 Gap/实验；在知识库删除该临时论文并二次确认。
4. 确认回到 2 篇论文、505 chunks、505 ready vectors，missing/orphan/failed 均为 0。

讲解重点：删除会清理论文、revision、chunks、向量和托管 PDF；历史引用会保留但明确标记“来源已删除”。

## 4. 外部服务降级话术（1 分钟）

- **arXiv warning / 空结果**：外部检索没有返回可验证论文，系统保留 warning，并只使用本地真实证据；这不是 3 秒 timeout，当前超时为 30 秒。
- **OpenAlex 空图**：OpenAlex 当次没有返回 canonical works，系统展示空图或 warning，不制造引用关系。
- **DeepSeek 不可用**：保留已检索证据但不生成研究结论，提示 provider unavailable。
- **讯飞 embedding 不可用**：上传任务进入可重试失败，不把 fallback 向量污染正式索引；恢复后使用原任务 retry。
- **OCR unavailable**：演示文件是文本 PDF，不依赖 OCR；纯扫描件需要安装 OCR 依赖后再演示。

## 5. 禁止操作

- 不删除两篇基线论文。
- 不删除、移动或修改 `data/cleanup-backup-20260731T184309/`。
- 不回显 `.env`、API key、签名 URL 或 token。
- 不用基线论文测试破坏性失败路径。
- 不把 synthetic/mock 结果描述为真实外部证据。
- 不在演示前临时切换 embedding provider/model；这会造成索引 profile 不兼容。

## 6. 收尾检查（30 秒）

- `/health/ready` 仍为 200/ready。
- papers/chunks/ready vectors 回到 `2/505/505`。
- vector missing/orphan/failed 为 `0/0/0`。
- 两篇基线 PDF 与 cleanup backup 目录仍存在。
- 若 Research Plan 新增了 Gap/实验历史，保留这些正常演示成果，不为恢复旧计数而删除。

## 7. 已验证的真实失败模式

- `RUN_LIVE_SMOKE=true` 单独运行时，测试中的 `Settings(_env_file=None)` 不会自动读取 `.env`；应在测试进程中安全加载环境变量，且不得打印变量值。
- 特定中文研究主题可能得到 `arXiv returned no results.`；只要原因不是 timeout，且页面正确降级到本地证据，即属于预期行为。
- OCR 依赖当前未安装；文本 PDF 路径已验证可用。

T3/T4 的真实 provider 与上传记录见 `docs/live-validation-t3-t4-2026-08-03.md`。

## 8. 2026-08-03 实走记录

- 全清单从服务启动到最终健康核验约 **11 分 23 秒**；其中浏览器内五模块连续演示 **9 分 16 秒**，满足不超过 15 分钟的验收要求。
- 启动后 `/health/ready` 为 `200/ready`；演示结束后仍为 `200/ready`。
- 论文问答：使用 `1_VRD_Language_Priors_Lu2016.pdf`，回答返回 3 个本地来源，页面引用覆盖第 5、12、19 页。
- 研究路线：两篇基线论文共同运行，得到 3 张课题执行卡、3 组实验建议和 9 个执行步骤；arXiv 多次返回空结果 warning，但原因不是 timeout，本地证据路径正常继续。因 1 组建议缺少可核验支持证据，最终只持久化 2 组实验，符合 fail-closed 设计。
- 复现实验室：标准复现返回 11 个报告区段、7 个步骤，`unknown` 字段为 0，未运行代码。
- 引用图谱：关键词 `retrieval augmented generation` 返回 15 个节点、6 条连线，未出现 warning。
- 知识库：上传临时纯文本 PDF 至 ready，产生 4 个论文片段；随后从 UI 二次确认删除，论文列表恢复为 2 篇，临时源文件与片段均已清理。
- 最终数据为 `2 papers / 505 chunks / 505 ready vectors`，`missing/orphan/failed=0/0/0`；两篇托管基线 PDF 和 `data/cleanup-backup-20260731T184309/` 均存在。
- Research Plan 的正常演示结果予以保留，最终为 12 个 Gap、2 个实验；没有为恢复旧历史计数而删除数据。
- 后端演示请求均为 `200` 或上传创建时的 `202`，未见 5xx/Traceback。日志中有两类非阻塞前端信息：Vite 在后端尚未启动完成时出现过一次健康探针 `ECONNREFUSED`；重复的 arXiv 空结果 warning 触发 React duplicate-key console warning，但没有中断或改变本次演示结果。
