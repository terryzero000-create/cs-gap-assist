# T3/T4 真实链路验证记录

执行时间：2026-08-03（Asia/Shanghai）

范围：比赛可用版的真实上传回归与真实外部服务 live smoke。本记录不包含任何密钥或敏感配置值。

## T3 真实上传回归

- 使用临时生成的 1 页纯文本 PDF：`cs-gap-assist-t3-regression.pdf`（1643 bytes，不含个人或生产信息）。
- 从前端“论文问答”上传，后端返回 `202 Accepted`，前端轮询上传任务直至论文 `ready`。
- 入库结果：新增 1 篇论文、5 个 chunks、5 个 ready vectors；上传及 embedding 期间后端日志无 HTTP 500、Traceback 或 ERROR。
- 从前端“知识库”执行永久删除；界面确认同时移除 5 个论文片段。
- 删除后基线恢复：2 篇论文、505 个 chunks、505 个 ready vectors；`missing_chunk_count=0`、`orphan_vector_count=0`、`failed_chunk_count=0`。

结论：T3 通过。`XFYUN_EMBEDDING_CONCURRENCY=1` 下真实讯飞 embedding 上传闭环稳定，临时论文已完整清理。

## T4 真实外部服务 smoke

### Provider smoke

- 直接执行 `RUN_LIVE_SMOKE=true pytest backend/tests/live/test_live_providers.py` 时，测试中的 `Settings(_env_file=None)` 不会读取 `.env`，因此在只设置该开关的 PowerShell 进程里会被判定为讯飞/OpenAlex 凭据缺失；这不是外部服务请求失败。
- 在测试进程中安全加载 `.env`（不输出变量值）后重跑：`2 passed in 7.05s`。
- 讯飞：返回 1 个 2560 维真实向量，未 fallback。
- OpenAlex：返回 canonical works，无 warning。
- DeepSeek：真实最小生成请求返回 `LIVE_OK`，无 warning。
- arXiv：以 `retrieval augmented generation` 检索返回 3 篇真实论文，无 warning。

### 前端 Research Plan

- 选中两篇基线论文，研究方向为“视觉关系检测在跨域场景中的鲁棒性评估与改进”。
- `/api/v1/research-plan-agent/run` 返回 HTTP 200。
- 结果包含 3 个 Research Gaps、2 个有效实验建议、5 篇后续阅读推荐和 3 张课题执行卡。
- 针对该中文主题的 arXiv 检索返回 `arXiv returned no results.`，页面按设计降级为“仅使用本地真实证据”；warning 原因不是 timeout。
- 本次运行把 Gap 历史从 5 条增加为 8 条；实验历史仍为 0 条，符合路线图中 T7 尚未处理前的已知持久化行为。

结论：T4 通过。四个外部 provider 均真实可用；Research Plan 的主题检索出现空结果降级，但不再因 3 秒 timeout 失败。

## 最终状态

- `/health/ready`：HTTP 200，`status=ready`。
- papers/chunks/vectors：`2 / 505 / 505`。
- vector missing/orphan/failed：`0 / 0 / 0`。
- 后端 T3/T4 期间无 HTTP 500、Traceback 或 ERROR。
- `data/cleanup-backup-20260731T184309/` 未改动。
