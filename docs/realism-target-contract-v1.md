# Realism Target Contract v1

真实性目标与回归 gate 是两套独立系统：

```text
回归 gate
  问：代码或参数是否改变了既有结果？

真实性目标
  问：当前长期分布距离经过来源核验的目标有多远？
```

不能用回归基线冒充真实篮球，也不能因为真实性评分改善就忽略不可解释的代码漂移。

## 目标集状态

目标集只有两种状态：

```text
draft
active
```

`draft` 可以只有 `planned_metrics`，不会产生分数或通过结论。

`active` 必须：

- 至少包含一个来源；
- 至少包含一个数值目标；
- 不再包含待定义指标；
- 每个指标引用已登记来源；
- 每个来源具有日期、定位信息和 64 位 SHA-256。

因此没有来源的临时数字不能被切换成 active。

## 来源契约

每个来源记录：

```text
source_id
label
origin
artifact_path
retrieved_on
content_sha256
```

`origin` 记录公开页面或原始发布方；`artifact_path` 必须是相对目标文件目录的可移植本地路径，且不能包含 `..`。加载目标集时会读取该文件并现场核对 `content_sha256`。因此 URL、网页标题或人工描述不能替代实际参与计算的固定输入快照。

## 指标契约

每个目标记录：

```text
metric
lower
target
upper
weight
required
source_id
```

必须满足：

```text
lower <= target <= upper
weight > 0
```

普通指标和份额指标均复用批量审计中的稳定名称，例如：

```text
points_per_100_possessions
turnover_rate
shot_zone_share.THREE
player_usage_share.home.1
```

## 损失函数

指标落在 `[lower, upper]` 内时损失为 0。落在区间外时：

```text
scale = max(upper - lower, abs(target) * 0.05, 1e-12)
normalized_distance = distance_to_interval / scale
```

总体分数为加权 normalized-distance RMSE。报告按偏差从大到小排列指标。

`required=true` 的指标越界会导致 active 目标失败；非 required 指标只贡献连续损失。draft 目标的 `gate_passed` 永远为 `null`。

## 本地命令

无数值的完整 draft 模板仍可用于检查契约：

```powershell
.\tools.ps1 audit-score `
  data/baselines/model-audit-demo-0.4.0.json `
  experiments/realism-targets-template-v1.json `
  --output work/runs/realism-draft-report.json
```

模板位置：

```text
experiments/realism-targets-template-v1.json
```

已固定 NBA.com 来源的首个 active 核心目标可以直接评分：

```powershell
.\tools.ps1 audit-score `
  data/baselines/model-audit-demo-0.4.0.json `
  experiments/nba-2024-25-regular-season-core-v1.json
```

来源、分母和重建方法见
[`nba-reference-targets-v1.md`](nba-reference-targets-v1.md)。尚未取数的指标不能因为核心
目标已经激活而手工补入。

## 首批计划指标

- 场均球队球权；
- 每百球权得分；
- 总命中率与三分命中率；
- 失误率；
- 进攻篮板率；
- 每次命中助攻数；
- 盖帽率和抢断率；
- 篮下、中距离和三分出手份额。

战术家族和 Coverage 是本模拟器内部语义，目前不直接假定存在可一一映射的公开 NBA 目标。

## 后续取数流程

1. 确认联盟、赛季、常规赛/季后赛和球队比赛样本。
2. 下载或保存固定源数据。
3. 记录原始文件 SHA-256。
4. 用独立脚本按与模拟审计相同的分母口径计算目标。
5. 审核区域映射、回合定义和篮板/失误分母。
6. 将目标集从 draft 切换为 active。
7. 首次评分后保存报告，但不覆盖代码回归基线。
