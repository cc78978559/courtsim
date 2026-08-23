# 本地工具链

## 原则

- 模拟器运行时保持零第三方依赖。
- 开发工具安装在项目内 `.venv`，不污染全局 Python。
- `requirements/dev.lock` 固定当前开发环境；`dev.in` 表达允许升级的范围。
- `tools/wheelhouse` 保存本机离线安装包，但不进入版本控制。
- 所有常用操作统一经过根目录 `tools.ps1`。

## 初次准备

```powershell
.\tools.cmd bootstrap
.\tools.cmd doctor
.\tools.cmd check
```

`bootstrap` 优先使用本地 wheelhouse。没有本地安装包时才会联网下载。
`tools.cmd` 优先使用已安装的 PowerShell 7 (`pwsh`)，缺失时回退 Windows PowerShell；
两者都只对当前子进程绕过脚本策略，不修改机器配置，并原样返回门禁退出码。

## 日常命令

```powershell
.\tools.cmd check-static
.\tools.cmd check-unit
.\tools.cmd check-fast
.\tools.cmd check-changed
.\tools.cmd check-timed
.\tools.cmd check-slow
.\tools.cmd check-franchise
.\tools.cmd check
```

`check-fast` 排除 `slow` 标记；`check` 依次执行格式检查、静态检查、严格类型检查、
全部测试和覆盖率门槛。失败时控制台只保留有界摘要，完整输出写入
`work/logs/tooling/`。

`check-fast` 和 `check-timed` 会把附加参数继续传给 pytest。`check-changed` 对仅修改
测试文件的工作树执行定向检查；源码、依赖、配置或工具脚本发生变化时会保守回退到
完整快速门禁。`check-timed` 将逐阶段耗时写入被 Git 忽略的
`work/metrics/check-timed-latest.json`。

若 `.venv` 缺模块或 `pip check` 失败，使用 `bootstrap --repair`。损坏环境会先移动到
`work/quarantine/venv-<timestamp>`，不会直接删除，然后按锁文件重新创建；健康环境
会立即返回，不重复联网安装。

## 机器状态与 NBA 产物

```powershell
.\tools.cmd project-status
.\tools.cmd nba-data sync <manifest.json>
.\tools.cmd nba-data build <manifest.json> <summary.json>
.\tools.cmd nba-data status <manifest.json> --output <summary.json>
.\tools.cmd nba-quick-sim-status <checkpoint.json>
.\tools.cmd nba-quick-sim-compare <checkpoint.json> <reference.json>
.\tools.cmd nba-franchise-checkpoint-verify <checkpoint.json.gz>
.\tools.cmd nba-franchise-status <manifest.json>
```

这些入口默认输出紧凑 JSON，并在报告状态前验证治理哈希或产物哈希。
`nba-data` 原始缓存位于 `.cache/nba-data/` 且不进入 Git；构建过程逐行聚合，
详情见 [NBA 本地数据流水线](nba-local-data-pipeline-v1.md)。

## 模拟产物工具

```powershell
.\tools.cmd replay work/runs/demo/events.jsonl --possession 3
.\tools.cmd verify work/runs/demo/manifest.json
```

Replay只读取已保存事件，不重新运行模拟。Verify会重新计算清单中输入和输出文件的SHA-256。

## CI 分片

CI 将静态检查、Windows 快速测试、Ubuntu 快速 coverage、Ubuntu 慢测 coverage 和
package smoke 分开调度。两份 Ubuntu coverage 产物最后合并并执行同一个 85% 门槛；
因此分片只改变调度，不减少测试集合，也不改变既有 Ubuntu、Windows 和 package
治理证明名称。

## CLI 模块边界

顶层 `courtsim.cli` 负责通用命令路由和统一异常到退出码的映射。产物生命周期命令在
`courtsim.cli_artifacts` 注册并执行，NBA 经理研究命令在 `courtsim.cli_manager`
注册并执行。新增同族命令应放进对应模块并加入其不可变命令集合，避免继续扩大顶层
parser 和 `main()` 分支。

## Trace边界

正式事件记录“发生了什么”，Decision Trace记录“AI为什么这样选择”。Trace包含候选项、权重、概率、选中项和随机流名称，默认批跑时可以关闭。
