# NBA 本地数据流水线 v1

## 目标

原始逐回合文件只在本机缓存和处理。CourtSim、Git 和 AI 上下文只接收带来源哈希的
小型 JSON 汇总，从而避免把几十万行数据放进对话或模型上下文。

流水线没有运行时第三方依赖，支持普通 CSV、`.csv.gz`、`.csv.xz`、ZIP，以及只含
一个目标 CSV 的 `.tar.gz` / `.tar.xz`。

## 推荐来源

个人研究优先下载 SportsDataverse `hoopR` 的预构建赛季文件，或
`shufinskiy/nba_data` 的赛季压缩包。不要把原始文件提交到 CourtSim 仓库，也不要
依赖模拟运行时联网。

仓库已包含一个经过本机连接、内容哈希和表头验证的可选清单：
`experiments/nba-data/shufinskiy-nbastatsv3-2024.json`。它不需要账号或 API Key，
原始数据仍只进入本地缓存。

回合级清单为 `experiments/nba-data/shufinskiy-pbpstats-2024.json`。该来源会为同一
回合的每条描述重复聚合字段，因此清单使用复合键去重，不能直接对原始行求和。

投篮位置清单为 `experiments/nba-data/shufinskiy-shotdetail-2024.json`，用于生成篮下、
非限制区油漆区、中距离、底角三分和弧顶三分的出手占比及命中率。

## 工作流

1. 将下载文件放在仓库外，或放入被忽略的 `.cache/nba-data`；本地 `path` 相对清单
   文件所在目录解析。
2. 复制示例清单并填写本地 `path` 或 HTTPS `url`。
3. 首次同步、流式构建，然后检查状态：

```powershell
Copy-Item experiments/nba-data/hoopr-pbp-manifest.example.json work/nba-data.json
# 将 nba_pbp_2025.csv.gz 放到 work/，与清单同目录
.\tools.cmd nba-data sync work/nba-data.json
.\tools.cmd nba-data build work/nba-data.json work/nba-2024-25-summary.json
.\tools.cmd nba-data status work/nba-data.json `
  --output work/nba-2024-25-summary.json
```

直接使用已验证的无 Key 2024-25 端点：

```powershell
.\tools.cmd nba-data sync experiments/nba-data/shufinskiy-nbastatsv3-2024.json
.\tools.cmd nba-data build experiments/nba-data/shufinskiy-nbastatsv3-2024.json `
  work/nba-2024-25-events-summary.json
.\tools.cmd nba-data audit work/nba-2024-25-events-summary.json `
  experiments/sources/nba-2024-25-team-core.json `
  experiments/sources/nba-2024-25-team-free-throws.json `
  work/nba-2024-25-source-audit.json
```

`audit` 使用固定 NBA 球队总量做独立来源核对，并把重合指标分为 `pass`、
`warning` 和 `rejected`。只有通过指标进入 `promotion`；例如逐事件篮板包含球队及
死球篮板，不能直接冒充传统球队篮板总量。

回合级构建和审计：

```powershell
.\tools.cmd nba-data sync experiments/nba-data/shufinskiy-pbpstats-2024.json
.\tools.cmd nba-data build experiments/nba-data/shufinskiy-pbpstats-2024.json `
  work/nba-2024-25-possession-summary.json
.\tools.cmd nba-data audit-possessions work/nba-2024-25-possession-summary.json `
  experiments/sources/nba-2024-25-team-core.json `
  work/nba-2024-25-possession-audit.json
```

`pbpstats` 的实际回合边界与 NBA 球队 `POSS` 汇总口径不同。审计不会把两者静默
混合：回合时长和犯规率保留为来源独有指标，只有与固定球队总量对齐的指标才进入
`reconciled_metrics`。

投篮区域构建和审计：

```powershell
.\tools.cmd nba-data sync experiments/nba-data/shufinskiy-shotdetail-2024.json
.\tools.cmd nba-data build experiments/nba-data/shufinskiy-shotdetail-2024.json `
  work/nba-2024-25-shot-zone-summary.json
.\tools.cmd nba-data audit-shots work/nba-2024-25-shot-zone-summary.json `
  experiments/sources/nba-2024-25-team-core.json `
  work/nba-2024-25-shot-zone-audit.json
.\tools.cmd nba-data build-shot-profiles work/nba-2024-25-shot-zone-summary.json `
  work/nba-2024-25-shot-zone-audit.json `
  work/nba-2024-25-team-shot-profiles.json
```

`audit-shots` 用球队总量核对球队数、比赛数、投篮和三分的命中/出手及命中率。
区域分布没有第二个固定来源可逐项核对，因此明确保留在 `source_only_metrics`，供模拟
校准使用，不伪装成多来源共识。

投篮清单使用 `TEAM_NAME` 本地分组；`build-shot-profiles` 只接受哈希匹配且状态为
`passed` 的审计，将每队相对联盟的 RIM/MIDRANGE/THREE 分布转换为小型倾向偏移。
`NBAQuickSimExecutor.shot_zone_profiles` 可显式加载这些画像；画像只作用于当次模拟的
临时球员倾向，不改写生涯能力，也不会污染后续赛季存档。
`execute_nba_franchise_season(..., shot_zone_profiles=profiles)` 会在每赛季重建阵容后应用
同一份画像，因此交易、成长和轮换仍先于临时倾向调整发生。默认值为 `None`，旧模拟
结果不变。

基线和画像候选应使用完全相同的 `QuickSimBatchSpec` 分别生成检查点，再做配对比较：

```powershell
.\tools.cmd nba-quick-sim-paired-diff `
  work/quick-sim-baseline.json `
  work/quick-sim-shot-profiles.json `
  work/quick-sim-shot-profile-diff.json
```

比较器要求两个批次均完整，且规格、赛季编号和派生种子逐项相同；报告提供六项快速
模拟指标的基线均值、候选均值、平均差及单赛季差值范围。

快速模拟总览不能证明投篮画像更真实。标准时长执行后，应分别把常规赛比赛结果交给
`audit_game_results`，再比较每队区域误差：

```powershell
.\tools.cmd nba-shot-profile-evaluate `
  work/standard-baseline-audit.json `
  work/standard-profiled-audit.json `
  work/nba-2024-25-team-shot-profiles.json `
  work/standard-shot-profile-evaluation.json
```

评估器计算全部 30 队 × 3 区域的 RMSE、MAE、逐区域 RMSE 和改善/恶化计数。只有
`candidate_rmse` 低于 `baseline_rmse` 才标记为 `improved`；短时长 smoke 不可替代
标准时长、多种子的校准结论。

多个种子分别生成评价报告后，使用 pooled RMSE 汇总，避免直接平均各批误差：

```powershell
.\tools.cmd nba-shot-profile-evaluate-batch `
  work/shot-profile-batch.json `
  work/seed-1-evaluation.json `
  work/seed-2-evaluation.json `
  work/seed-3-evaluation.json
```

批报告保留改善、退化和不变的运行数，并分别汇总逐区域及逐队 RMSE。

当模拟的联盟区域基线与真实联盟均值存在结构差异时，不应直接把“真实球队相对
真实联盟均值”的偏移应用到模拟。`calibrate_nba_shot_profiles` 使用完整基线审计，
按每队 `target_share / simulated_baseline_share` 重算中心化对数偏移，并限制最大
绝对偏移。用于重算的基线种子必须与评价种子分离；禁止在同一批数据上生成偏移并
报告其拟合改善。`calibration_strength` 可在 `(0, 1]` 内统一收缩偏移，但只能依据
独立校准批选择，最终仍须在未参与选择的留出种子上评价。
`zone_calibration_strengths` 按 `RIM/MIDRANGE/THREE` 顺序提供 `[0, 1]` 分区收缩；
分区参数同样必须由校准批选择，并由另一组留出种子确认。
推荐的新校准坐标是以 `THREE` 为锚点的 `log(RIM/THREE)` 与
`log(MIDRANGE/THREE)`。传入 `contrast_calibration_strengths` 后只产生这两个可识别
对比，三分评分固定为零；对比强度与旧分区强度互斥，避免重复控制同一自由度。

冻结参数可物化为带来源哈希的 v2 画像，之后直接由现有加载器和快速模拟执行器使用：

```powershell
.\tools.cmd nba-shot-profile-calibrate `
  work/nba-2024-25-team-shot-profiles.json `
  work/standard-shot-baseline-audit.json `
  work/nba-2024-25-team-shot-profiles-calibrated.json
```

v2 产物记录基础画像与基线审计的 SHA-256、算法版本、最大偏移、全局强度及两个对比
强度；默认值就是下述冻结验证采用的 `0.75 / (1.0, 0.75)`。

正式 A/B 不再依赖 `work/` 临时脚本，也不会为投篮校准额外模拟 play-in 和季后赛：

```powershell
.\tools.cmd nba-shot-profile-run `
  work/nba-2024-25-team-shot-profiles-calibrated.json `
  --seed 20260820 `
  --output work/runs/shot-profile-20260820 `
  --quiet
```

命令只运行两份配对的 30 队常规赛，写出基线审计、候选审计、评价和带输入/输出
SHA-256 的 manifest。`nba-shot-profile-evaluate`、`evaluate-batch`、`calibrate` 与 `run`
均支持 `--quiet`；不使用静默模式时也只打印单行摘要，不再把完整 30 队 JSON 写入终端。

### 冻结校准验证（2026-08-01）

参数选择严格分离为三组：`20260801` 生成基线校准，`20260802–05` 仅用于开发
选择，随后冻结 `calibration_strength=0.75`、`contrast_calibration_strengths=(1.0,
0.75)`。最终留出 `20260810–19` 在参数冻结后才读取。

- 10 个短时长留出种子全部改善，pooled RMSE 改善 33.52%，三区均改善；
- 3 个标准时长留出种子全部改善，合计 7,380 场配对比赛零中止；
- 标准 pooled RMSE 从 0.10021 降至 0.06384，改善 36.30%；
- 标准篮下、中距离、三分 RMSE 分别改善 0.03755、0.05642、0.00164；
- 30 队 pooled RMSE 全部改善。

这些留出种子现已被读取，后续不得继续用于选择参数；若再次调参，必须建立新的开发
批，并保留另一组未查看的最终测试种子。

默认缓存目录是 `.cache/nba-data/<dataset_id>/`。跨机器接续时传递原始数据文件，
或在新机器上再次执行 `sync`；Git 只需要传递清单和处理代码。

## 安全与增量规则

- URL 只允许 HTTPS。
- 清单可固定来源 SHA-256；不匹配的下载会立即删除。
- `sync --offline` 只接受已存在且通过校验的缓存。
- `sync --force` 显式重新复制或下载来源；默认优先复用缓存。
- `build` 流式逐行聚合，不会把完整赛季载入内存。
- 输入文件和清单哈希未变化时，`build` 直接复用现有汇总。
- `status` 只读取文件元数据与哈希，不读取原始 CSV 行。
- `--force` 可显式重建。

## 聚合清单

`build.metrics` 支持：

- `count`：计数匹配行；
- `distinct_count`：统计某列非空唯一值；
- `sum`：对某列流式求和；
- `clock_delta_sum`：将 `MM:SS` 起止时钟转换为秒并求和；
- `ratio`：用两个已定义指标相除。

`build.deduplicate_by` 可声明复合去重键。此模式仍逐行读取压缩 CSV，但会在内存中
保留已见键的 SHA-256 摘要，而不是保留完整原始行。

`build.group_by` 可声明一个非空分组列；流水线仍只流式保留各组聚合状态，并在输出的
`groups` 中按键稳定排序，不把原始行载入内存。

条件支持 `equals`、`not_equals`、`in`、`contains`、`not_contains`、
`contains_ci`、`not_contains_ci` 和 `truthy`；`_ci` 变体不区分大小写。
列名或事件文本必须与下载文件实际 schema 对齐；来源升级导致列变化时，构建会明确
失败，不会静默产生错误指标。

输出中的 `local_reduction.context_reduction_ratio` 是原始文件字节数相对紧凑汇总
的缩减比例，用于工程上下文预算，不冒充精确的模型 Token 计数。
