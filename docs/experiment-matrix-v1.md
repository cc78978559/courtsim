# 实验矩阵 v1

实验矩阵用于顺序调度多阵容、多参数版本的本地模型审计。cell 之间暂不并发；
每个 cell 内部仍可使用 `workers`，避免嵌套进程池。

## 运行与续跑

```powershell
.\tools.ps1 experiment-matrix `
  experiments/matrices/demo-0.7.0-profile-smoke.json `
  --output work/matrices/demo-0.7.0-profile-smoke

.\tools.ps1 experiment-matrix `
  experiments/matrices/demo-0.7.0-profile-smoke.json `
  --output work/matrices/demo-0.7.0-profile-smoke `
  --resume
```

所有 cell 成功时返回 `0`；至少一个 cell 失败时继续执行其余 cell，最后返回 `8`。

## 规范

```json
{
  "format_version": 1,
  "matrix_id": "example-matrix",
  "base_directory": "../..",
  "master_seed": 20260728,
  "defaults": {
    "schema": "data/model_schema_demo_v1_5.json",
    "profile": "examples/calibration_lineup_v1.json",
    "games": 100,
    "workers": 4,
    "start_index": 0,
    "trace_mode": "aggregate-only",
    "clock": {
      "regulation_periods": 4,
      "period_seconds": 720,
      "possession_seconds": 15
    }
  },
  "targets": [
    "experiments/nba-2024-25-regular-season-core-v1.json"
  ],
  "cells": [
    {
      "cell_id": "candidate-a",
      "parameters": "work/candidates/a.json"
    },
    {
      "cell_id": "candidate-b",
      "parameters": "work/candidates/b.json",
      "profile": "examples/another_lineup.json"
    }
  ]
}
```

`base_directory` 相对于规范文件所在目录。cell 必须指定 `cell_id` 和 `parameters`，
可以覆盖默认 `schema` 与 `profile`。cell ID 只能使用小写 ASCII 字母、数字、
下划线和连字符，并且必须以字母开头。

每个 cell 的比赛种子由以下信息派生：

```text
matrix master_seed
"matrix-cell"
cell_id
```

因此 cell 排序、失败或新增其他 cell 不会改变已有 cell 的结果。

严格反事实比较可为多个 cell 指定相同的可选 `seed_group`：

```json
{
  "cell_id": "candidate-a",
  "parameters": "work/candidates/a.json",
  "seed_group": "paired-comparison"
}
```

此时种子派生键由 `cell_id` 改为 `seed_group`。同组 cell 使用相同比赛种子，适合
只改变参数或阵容的共同随机数比较。未声明 `seed_group` 的旧规范、计划哈希和种子
保持不变。普通候选排名不要求共同种子；反事实门禁必须要求。

## 产物

```text
matrix-report.json
cells/<cell-id>/cell-result.json
cells/<cell-id>/run-<plan-hash>/audit.json
cells/<cell-id>/run-<plan-hash>/manifest.json
cells/<cell-id>/target-001.json
```

`cell-result.json` 保存完整计划、输入哈希、目标哈希、派生种子、run manifest、
audit 哈希和各目标评分。`matrix-report.json` 汇总完成、失败和复用数量。

配对种子的反事实差异门禁见 `matrix-contrast-v1.md`。

## 安全续跑

`--resume` 只在以下条件全部满足时复用 cell：

1. cell 状态为 `completed`；
2. 计划哈希匹配；
3. schema、参数、球员和目标文件哈希未变化；
4. run manifest 验证通过；
5. audit 哈希匹配；
6. 所有目标评分文件哈希匹配。

任何条件不满足都会重跑该 cell。失败 cell 永远不会被当成已完成状态复用。

现实目标未通过不会使调度器本身失败，因为矩阵的职责是生成完整比较结果；
目标是否通过记录在每个 target report 中，应由后续选择或晋升工具判断。

## 候选排名

```powershell
.\tools.ps1 matrix-rank `
  work/matrices/demo-0.7.0-profile-smoke/matrix-report.json `
  --output work/matrices/demo-0.7.0-profile-smoke/ranking.json
```

排名器会再次验证：

- 矩阵规范及哈希；
- cell 计划哈希和全部输入文件；
- run manifest 和 audit；
- 目标来源和评分文件；
- 由 `audit.json + target set` 重新计算的评分。

候选至少有一个 active target、所有 active gate 通过且必需指标零失败，才具备
资格。排序依次使用：

1. 合格候选优先；
2. 必需指标失败数更少；
3. 失败的 active target 更少；
4. 到所有目标中心的加权 RMSE 更低；
5. cell ID 只用于稳定展示。

区间门禁仍是硬约束；目标中心距离只用于区分同样通过门禁的候选。若最佳分数完全
相同，报告列出并列候选。没有合格候选时返回退出码 `9`。

排名报告明确保存 `"automatic_promotion": false`。工具只提供证据和推荐，不会
修改正式参数、实验注册表或冻结基线。

## cell 级目标与风格覆盖

cell 可以用非空 `targets` 列表覆盖矩阵级默认目标。这用于不同阵容分别承担不同
球队风格目标。异构目标不能比较中心 RMSE，因此 `matrix-rank` 会明确拒绝这种矩阵。
使用以下命令生成完整性校验后的覆盖报告：

```powershell
.\tools.ps1 matrix-style-coverage `
  work/matrices/<name>/matrix-report.json `
  --output work/matrices/<name>/style-coverage.json
```

覆盖报告保留每个 cell 的逐指标方向和距离，并检测跨 cell 完全不变的指标，帮助
识别尚未参数化的结构常量。它不推荐候选，也不会自动晋升。

cell 还可以指定 `opponent_profile`。此时 `profile` 是被测主队，独立对手是客队；
未指定时客队继续复用 `profile`。配对对照工具可以在异构现实目标矩阵上运行，因为
它只比较共同种子的两个 audit，不会横向排名不同目标分数。

## 多种子稳健性审计

单次矩阵排名只能证明候选在一个比赛种子上成立。正式考虑冻结候选前，应对全部已
完成 cell 运行独立种子复现：

```powershell
.\tools.ps1 matrix-robustness `
  work/matrices/demo-0.7.0-profile-smoke/matrix-report.json `
  --output work/matrices/demo-0.7.0-profile-smoke-robustness `
  --replicates 5 `
  --minimum-pass-rate 1.0

.\tools.ps1 matrix-robustness `
  work/matrices/demo-0.7.0-profile-smoke/matrix-report.json `
  --output work/matrices/demo-0.7.0-profile-smoke-robustness `
  --replicates 5 `
  --minimum-pass-rate 1.0 `
  --resume
```

`replicate-000` 复用矩阵原始 manifest 和 audit，不重复消耗计算。后续复现种子为：

```text
derive_seed(cell 原始种子, "robustness-replicate", replicate_index)
```

因此增加复现次数不会改变已有复现结果。每次复现仍使用原 cell 冻结的 schema、
参数、阵容、目标、时钟、比赛数、worker 数和 trace 模式，并重新验证 manifest、
audit 与目标评分。每个复现结果及总报告均记录文件哈希。

默认稳健资格要求：

- 至少运行 2 个复现；
- 复现通过率为 `1.0`；
- 任一复现的必需指标失败数均为 `0`。

还可用 `--maximum-center-rmse` 限制最差目标中心 RMSE，用
`--maximum-center-rmse-stddev` 限制跨种子波动。排序依次考虑稳健资格、通过率、
最差必需失败数、最差中心 RMSE、平均中心 RMSE 和标准差。完全相同则保留并列。

任一 cell 执行失败时，其他 cell 仍继续，命令最终返回 `10`；全部执行成功但没有
稳健合格候选时返回 `11`；存在稳健候选时返回 `0`。报告始终明确保存
`"automatic_promotion": false`，不会自动修改正式参数或基线。

### 安全续跑

`--resume` 按复现粒度判断是否复用。必须同时满足：

1. 复现编号、cell ID、派生种子和来源类型匹配；
2. manifest 的种子、比赛索引、时钟、trace 模式和三个输入文件完全匹配；
3. manifest 自身及其全部输入、输出哈希验证通过；
4. audit 路径和哈希匹配；
5. 使用当前 `audit + target set` 重新计算的全部评分与落盘评分逐项相同；
6. `replicate-result.json` 与重新汇总的结果完全相同。

任一条件不满足只会重跑对应复现。若最终 `robustness-report.json` 尚未写出，例如进程
在中途退出，仍可从已完成且验证通过的复现继续。若最终报告已经存在，则源矩阵和
全部稳健性门槛配置也必须与原报告完全一致；配置漂移会直接拒绝续跑，应使用新的
输出目录。报告的 `executed_replicates` 和 `reused_replicates` 用于审计本次恢复行为。
