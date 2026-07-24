# 矩阵反事实对比 v1

矩阵反事实对比用于回答“只改变阵容或参数后，模型指标是否按预期方向变化”。它不
判断候选是否符合 NBA 总体均值，而是验证球员属性和参数差异是否真实传导到比赛
分布。

## 共同随机数

参与同一对比的两个 matrix cell 必须声明相同 `seed_group`。工具还会确认比赛数、
比赛索引和时钟完全相同。不同种子的两个统计样本不能被报告为严格反事实差异。

delta 固定定义为：

```text
candidate metric - baseline metric
```

## 对比规范

```json
{
  "format_version": 1,
  "kind": "courtsim-matrix-contrast-spec",
  "contrast_set_id": "example-contrast-v1",
  "comparisons": [
    {
      "contrast_id": "shooter-vs-neutral",
      "baseline_cell_id": "neutral",
      "candidate_cell_id": "shooter",
      "gates": [
        {
          "metric": "shot_zone_share.THREE",
          "minimum_delta": 0.1,
          "maximum_delta": 0.5
        }
      ]
    }
  ]
}
```

每个 comparison 至少包含一个 gate，同一 comparison 内指标不能重复。上下界必须
有限且 `minimum_delta <= maximum_delta`。可使用 `audit_metric_map` 暴露的标量、
区域份额、战术份额、防守覆盖份额和球员使用率指标。

## 运行

```powershell
.\tools.ps1 experiment-matrix `
  experiments/matrices/demo-0.7.0-profile-contrast.json `
  --output work/matrices/demo-0.7.0-profile-contrast

.\tools.ps1 matrix-contrast `
  work/matrices/demo-0.7.0-profile-contrast/matrix-report.json `
  experiments/contrasts/demo-0.7.0-profile-contrast-v1.json `
  --output work/contrasts/demo-0.7.0-profile-contrast
```

全部 comparison 和 gate 通过时返回 `0`；存在执行错误、非配对种子、未知指标或
delta 越界时仍写出完整报告，最后返回 `12`。

## 完整性与边界

工具首先调用矩阵排名完整性检查，重新验证矩阵规范、cell 计划、全部输入、
manifest、audit、目标来源和评分。对比报告另外保存矩阵、规范、ranking 和两侧
audit 的 SHA-256。

报告固定包含：

```json
{
  "paired_seed_required": true,
  "automatic_promotion": false
}
```

对比通过只说明该样本中的方向性契约成立，不说明效应在多个独立种子上稳定，也不
说明候选符合现实总体目标。正式冻结仍需目标门禁、矩阵排名和多种子稳健性审计。

首个 `demo-0.7.0` 契约比较平衡阵容与全中性模板，只冻结使用率、区域选择、进攻
篮板、盖帽和罚球出手率六个高信号方向。它是模型敏感性回归，不是真实球队校准。

## 多种子反事实稳健性

先对配对矩阵运行普通稳健性审计，再逐复现聚合反事实门禁：

```powershell
.\tools.ps1 matrix-robustness `
  work/matrices/demo-0.7.0-profile-contrast/matrix-report.json `
  --output work/matrices/demo-0.7.0-profile-contrast-robustness `
  --replicates 3

.\tools.ps1 matrix-contrast-robustness `
  work/matrices/demo-0.7.0-profile-contrast-robustness/robustness-report.json `
  experiments/contrasts/demo-0.7.0-profile-contrast-v1.json `
  --output work/contrasts/demo-0.7.0-profile-contrast-robustness.json `
  --minimum-pass-rate 1.0
```

聚合器不会信任上游的通过标记。它会重新验证每个
`replicate-result.json`、manifest、audit、种子、比赛索引和时钟，然后按相同
replicate 编号成对计算 delta。

每项 gate 报告：

- 通过复现数与通过率；
- delta 均值、最小值和最大值；
- delta 总体标准差；
- 是否达到全局 `minimum_pass_rate`。

任一对比执行失败或 gate 通过率不足时返回 `13`。报告仍固定保存
`"automatic_promotion": false`。

2026-07-24 的首个正式运行使用每个复现100场、3个共同种子。六项方向门禁均为
`3/3` 通过；平衡阵容自身也在三个种子上全部通过现实目标，而中性模板为 `0/3`。
该结果冻结的是合成阵容敏感性证据，不是多支真实球队的拟真结论。
