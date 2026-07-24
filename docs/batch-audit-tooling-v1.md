# Batch and Distribution Audit Tooling v1

阶段 9 建立长期使用的本地批量管理、测试和审计工具。当前参数仍未校准，因此本工具只冻结计算口径并生成基线，不内置“是否像 NBA”的结论。

## 索引化批次

每场比赛的种子只由以下信息确定：

```text
master_seed
"model-game"
game_index
```

因此：

- 运行顺序不会改变结果；
- 分片边界不会改变结果；
- 单场失败可以按 `game_index` 单独重跑；
- 不同机器只要输入和版本一致，就能合并结果。

核心接口：

```text
planned_game_seeds
sample_game_batch
sample_game_batch_indices
merge_game_batches
```

`game_indices` 必须非空、非负、唯一且升序。合并时会按索引重排，并拒绝重复索引或不同主种子的分片。

## 本地命令

快速 smoke：

```powershell
.\tools.ps1 model-audit `
  --games 2 `
  --periods 1 `
  --period-seconds 60 `
  --possession-seconds 15 `
  --output work/runs/model-audit-smoke
```

标准基线：

```powershell
.\tools.ps1 model-audit `
  --master-seed 20260723 `
  --games 50 `
  --workers 4 `
  --start-index 0 `
  --output work/runs/model-audit-demo-0.4.0
```

只需要校准汇总、不需要回放或磁盘分片合并时：

```powershell
.\tools.ps1 model-audit `
  --games 1000 `
  --workers 4 `
  --trace-mode aggregate-only `
  --output work/runs/calibration-fast
```

`aggregate-only` 保留并验证正式比赛事件直到汇总完成，但不保留 Decision Trace、
中间行动样本，也不写 `games.jsonl`。产物只有 `audit.json` 和 `manifest.json`；
因此不能用于 Replay，也不能交给 `model-audit-merge`。冻结回归基线必须继续使用
默认的 `full`。

## 性能基准

不要用一次手工计时判断性能变化。正式本地基准：

```powershell
.\tools.ps1 model-benchmark `
  --games 100 `
  --workers 4 `
  --warmups 1 `
  --repeats 3 `
  --trace-mode aggregate-only `
  --output work/benchmarks/demo-0.7.0
```

默认进行一次不计分预热和三次正式试验。每次试验使用相同输入、种子和比赛索引，
并必须产生相同的 `audit.json` SHA-256。`benchmark.json` 记录：

- Python、平台和逻辑 CPU 数；
- schema、参数和球员文件哈希；
- 时钟、worker、模式、预热和重复次数；
- 每次耗时、吞吐、manifest 和审计哈希；
- 中位吞吐、最小值、最大值和相对极差。

可为固定机器的持续性能检查增加：

```powershell
--minimum-games-per-second 20
```

门槛只适用于同一机器和相近后台负载，失败时命令返回退出码 `7`。跨机器比较应保存
报告，不应共用绝对门槛。

分片示例：

```powershell
.\tools.ps1 model-audit --games 25 --start-index 0  --output work/runs/audit-shard-0
.\tools.ps1 model-audit --games 25 --start-index 25 --output work/runs/audit-shard-1
```

磁盘合并：

```powershell
.\tools.ps1 model-audit-merge `
  --output work/runs/audit-merged `
  work/runs/audit-shard-0/manifest.json `
  work/runs/audit-shard-1/manifest.json
```

合并器会先验证所有 shard manifest 和文件哈希，然后检查主种子、模型、时钟和阵容一致；拒绝重复索引、内部缺失索引及种子不匹配。合并输入顺序不影响输出字节。

命令默认使用：

```text
data/model_schema_demo_v1_3.json
data/model_parameters_demo_0.4.0.json
examples/player_profile_v1.json
```

当前默认阵容为了验证工具链，会将同一个示例模板复制为双方各五名球员。因此输出是对称模型 smoke/baseline，不是球员多样性测试。

## 产物目录

每个批次原子写入：

```text
games.jsonl
audit.json
manifest.json
```

`games.jsonl` 每行包括：

```text
game_index
seed
canonical GameResult
```

`manifest.json` 保存：

- 主种子和游戏索引；
- 比赛时钟配置；
- 双方阵容；
- schema version、schema hash、parameter hash；
- schema 与参数文件 SHA-256；
- 输出文件 SHA-256 和字节数。

验证：

```powershell
.\tools.ps1 verify work/runs/model-audit-demo-0.4.0/manifest.json
```

## 审计指标

只使用自然完成的比赛计算分布，截断比赛单独计入 `aborted_games`：

- 场均球队得分与球队得分标准差；
- 场均球队球权；
- 每百球权得分；
- 总命中率与三分命中率；
- 失误率；
- 进攻篮板率；
- 每次命中助攻数；
- 盖帽率和抢断率；
- 出手区域份额；
- 行动片段级战术家族份额；
- 行动片段级 Coverage 份额；
- 各队球员终结/失误使用份额。

注意：战术和 Coverage 当前按行动片段计数。一次含进攻篮板的球权可能贡献多个战术样本。

## 基线差异与 Gate

生成逐指标差异：

```powershell
.\tools.ps1 audit-diff `
  data/baselines/model-audit-demo-0.4.0.json `
  work/runs/model-audit-demo-0.4.0/audit.json `
  --output work/runs/model-audit-demo-0.4.0/diff.json
```

执行显式范围 gate：

```powershell
.\tools.ps1 audit-check `
  work/runs/model-audit-demo-0.4.0/audit.json `
  experiments/model-audit-demo-0.4.0-regression-gates.json `
  --output work/runs/model-audit-demo-0.4.0/gate-report.json
```

Gate 必须显式声明 `kind`。当前的 `regression-not-realism` 只检测代码或参数是否偏离既有基线，不表示数值符合真实 NBA。失败时命令返回退出码 `5`。

份额指标使用如下名称：

```text
shot_zone_share.THREE
play_family_share.BALL_SCREEN
coverage_share.DROP
player_usage_share.home.1
```

## 并行确定性

`--workers N` 使用独立进程运行比赛。每个 worker 启动时只加载并验证一次模型与阵容；
每场任务只接收时钟、主种子和游戏索引。任务按有界 chunk 分发，输出仍按游戏索引
排序，worker 数量、chunk 边界和进程调度顺序不能进入随机地址。

## 测试分层

默认 `tools.ps1 check` 运行：

- 单节点和领域契约测试；
- 球权/比赛集成测试；
- 短比赛批量 smoke；
- 分片与整批逐位一致测试；
- 指标份额恒等式；
- 产物字节稳定与 manifest 哈希验证；
- 单 worker 与多 worker 字节一致；
- 磁盘分片合并及重复、缺失索引保护；
- 基线差异与通过/失败 gate；
- CLI 端到端 smoke。

标准 50 场或更大规模基线不进入每次提交的默认测试，以免拖慢开发；它应在参数或概率结构变更后手动运行并保存审计快照。

## 下一步工具升级

在增加新玩法机制之前，批量层后续应补：

- 从多个真实差异化球员档案装配阵容；
- 性能吞吐、异常率和截断率监控。
- 可中断批次的完成索引扫描与自动续跑；
- 多阵容、多参数版本的实验矩阵调度。
