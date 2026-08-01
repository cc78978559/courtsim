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
