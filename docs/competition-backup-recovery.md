# 比赛版备份与恢复说明

## 本次比赛版快照

2026-08-04 10:25（Asia/Shanghai）在停止前后端服务后创建了同一时点快照：

```text
data/competition-backup-20260804T1027/
```

快照包含：

- `app.db`：SQLite 数据库，完整性检查为 `ok`；
- `documents/`：两篇基线论文及托管文件；
- `chroma/`：与数据库 active chunks 对应的本地向量库；
- `MANIFEST.json`：创建时间、文件数和 `2/505/505` 数据基线。

现有 `data/cleanup-backup-20260731T184309/` 保持不变，不覆盖、不删除。

## 恢复步骤

1. 停止服务：`./stop-dev.ps1`，或 macOS/Linux 的 `./stop-dev.sh`。
2. 将当前 `data/app.db`、`data/documents/` 和 `data/chroma/` 移到一个明确的临时目录留存。
3. 将同一备份目录中的 `app.db`、`documents/` 和 `chroma/` 恢复到 `data/` 对应位置。
4. 启动服务：`./start-dev.ps1 -NoOpen`，或 macOS/Linux 的 `./start-dev.sh`。
5. 检查 `GET /health/ready` 为 `200` 且 `status=ready`；确认 `missing_chunk_count`、`orphan_vector_count` 和 `failed_chunk_count` 均为 `0`。
6. 运行 `python -m pytest backend/tests -q`，再按 `docs/demo-checklist.md` 做一次最小演示。

恢复时必须同时恢复 SQLite、托管文件和 Chroma，不能只恢复其中一个，否则论文、chunks 和向量可能产生不一致。不要把备份中的密钥、日志或 PID 文件复制回源码目录。

## 只读核验记录

本次快照创建后已在副本目录执行：

- SQLite `pragma integrity_check`：`ok`；
- 论文 / chunks / ready vectors：`2/505/505`；
- `documents/` 与 `chroma/` 均存在并包含文件；
- `MANIFEST.json` 与快照内容一致。
