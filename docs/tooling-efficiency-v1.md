# 本地工具效率优化 v1

## 日常反馈路径

```powershell
.\tools.cmd check-fast
```

`check-fast` 依次执行：

1. Ruff 格式检查；
2. Ruff lint；
3. mypy strict；
4. 排除 `slow` 标记的 pytest，不采集覆盖率。

成功时每个阶段只输出一行；任一阶段失败时回放该工具的完整诊断并保留退出码。
完整诊断同时写入 `work/logs/tooling/<stage>-latest.log`，控制台最多保留前 20 行和
末 80 行，避免代理上下文被重复 traceback 占满。2026-07-28 本机实测约 52 秒，
适合普通修改后的反馈。

更细的入口：

```powershell
.\tools.cmd check-static
.\tools.cmd check-unit
.\tools.cmd check-slow
.\tools.cmd check-franchise
```

`check-static` 只运行格式、lint 和严格类型检查；`check-unit` 只运行非慢速测试；
`check-slow` 运行完整 NBA 集成测试；`check-franchise` 只运行多赛季 franchise
测试。新增计算密集测试必须显式标记 `slow`，完整 30 队路径还应标记 `nba`，
多赛季闭环同时标记 `franchise`。

## 正式门禁

```powershell
.\tools.cmd check
```

正式门禁继续执行覆盖率采集并保持 `fail_under = 85`。成功输出压缩为：

```text
format: passed
lint: passed
typecheck: passed
tests: passed
coverage: 86%
```

失败时控制台输出摘要并给出完整日志路径。该命令用于阶段冻结、批量实验前和正式交付前。

`coverage` 子命令仍保留完整逐文件报告，供主动调查覆盖缺口时使用。

## 子命令维护

`tools.ps1` 不再复制 Python CLI 的完整命令白名单。PowerShell 只处理
bootstrap、测试和质量门禁等本地命令，其余命令统一转发给 `python -m courtsim`。
因此新增模拟或审计命令只需在 Python CLI 注册一次。

十个参数迁移命令由 `PARAMETER_MIGRATIONS` 注册表统一生成 parser 和执行入口，
不再各自复制四个位置参数与写入、加载、哈希输出逻辑。CLI 从约 757 行缩减到
统一注册入口，所有既有迁移命令保持兼容。

## 低上下文状态与 NBA 入口

```powershell
.\tools.cmd project-status
.\tools.cmd nba-quick-sim-status work/quick-sim/checkpoint.json
.\tools.cmd nba-quick-sim-compare work/quick-sim/checkpoint.json reference.json
.\tools.cmd nba-franchise-checkpoint-verify work/franchise/season-00002.json.gz
.\tools.cmd nba-franchise-status work/franchise/manifest.json
```

`project-status` 默认输出单行 JSON，验证冻结治理文件哈希并报告版本、Git
分支/脏状态、上下游距离、能力列表和推荐门禁。加 `--pretty` 才输出多行。
NBA 状态命令只读取、校验和汇总已有产物，不重新模拟；比较命令拒绝未完成 batch，
franchise 状态命令验证保留 checkpoint 的文件哈希、状态哈希和连续种子。

## 只读产物审计

```powershell
.\tools.cmd artifacts-audit work
.\tools.cmd artifacts-audit work --largest 20 `
  --output work/audits/artifact-inventory.json
```

工具只遍历和统计，不修改或删除文件。报告包括：

- 总文件数、字节数和 MiB；
- 按扩展名统计；
- 按一级目录统计；
- 最大文件列表。

优化前快照为 1,165 个文件、231.09 MiB，其中 JSONL 占约 227.6 MiB。
这说明后续清理策略应优先管理完整事件流，而不是小型 JSON 审计报告。

当前版本没有自动清理命令。删除或归档策略必须先定义正式基线、最近实验、
失败诊断和可重建缓存的保留规则，不能根据文件年龄直接删除。

## 无删除归档

归档采用两步式流程：

```powershell
.\tools.cmd artifacts-plan work work/audits/jsonl-plan.json `
  --include **/*.jsonl `
  --exclude runs/current/**

.\tools.cmd artifacts-archive `
  work/audits/jsonl-plan.json `
  D:\CourtSim-Archives\jsonl-history.zip

.\tools.cmd artifacts-verify-archive `
  D:\CourtSim-Archives\jsonl-history.zip

.\tools.cmd artifacts-restore `
  D:\CourtSim-Archives\jsonl-history.zip `
  D:\CourtSim-Restored\jsonl-history
```

第一步只生成计划，记录根目录、显式 include/exclude、相对路径、文件大小和
SHA-256。第二步要求所有源文件的大小和哈希仍与计划一致，然后创建 ZIP，并重新
读取 ZIP 内每个文件验证 CRC 和 SHA-256。

ZIP 使用固定元数据；相同计划和相同源文件会产生相同归档哈希。归档内包含
`_courtsim_archive_manifest.json`，记录源计划哈希和全部条目。

安全边界：

- 不接受隐式“全部文件”；至少提供一个 include；
- 拒绝绝对路径、`..`、保留清单名和符号链接；
- 输出已存在时拒绝覆盖；
- 空计划不能创建归档；
- 计划后源文件发生变化时拒绝归档；
- 创建失败时删除临时 ZIP；
- 成功后仍保留全部源文件；
- 不提供删除或 prune 命令。

独立验证不要求原始 `work/` 目录仍然存在，只依赖 ZIP 内 manifest、条目集合、
CRC、声明大小和逐文件 SHA-256。恢复前先执行同样的完整验证，只允许写入不存在
的新目录；文件先恢复到同目录下的临时目录，逐项复核后再原子改名。

恢复目录额外包含 `_courtsim_restore_receipt.json`，记录归档 SHA-256、文件数和
原始总字节数。恢复不会覆盖现有目录，也不会修改 ZIP。

当前只读候选计划为
`work/audits/all-jsonl-archive-review-plan.json`，包含 67 个 JSONL、
238,641,730 字节。它只是审阅清单，不代表这些文件已获准归档或删除。

## 当前验收

- `check-static`：秒级反馈；
- `check-fast`：2026-07-28 本机约 52 秒；
- `check`：包含计算密集的完整 NBA 和 franchise 回归，本机约 8–18 分钟；
- 快速测试：487 passed、1 skipped、3 slow deselected；
- 完整门禁：490 passed、1 skipped，共收集 491 项；
- 覆盖率门槛：85%；
- mypy strict 和 Ruff：通过；
- 成功门禁输出保持 3–5 行，失败全文落盘；
- 产物审计和 NBA 状态入口均为确定性、只读操作。
