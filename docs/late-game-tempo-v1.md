# 末节情境节奏 v1

## 语义

`demo-v1.9` 不引入新的玩法循环或逐帧球场。它只在既有球队节奏节点上加入一个
确定性的比赛状态修正：

- 仅在第四节最后 120 秒启用；
- 进攻方落后至少 6 分时，基础 `tempo + 20`；
- 进攻方领先至少 6 分时，基础 `tempo - 15`；
- 其余时刻保持基础 `tempo`；
- 最终评分限制在 `0..100`。

修正后的节奏仍通过既有 12/15/18 秒概率分布决定球权耗时，并继续使用
`RandomSlot.POSSESSION_DURATION = 24`。没有新增随机槽，也不改变球权内部的投篮、
失误、犯规、助攻或篮板结果。

## 可审计工具

```powershell
.\tools.ps1 tempo-policy-audit `
  data/model_schema_demo_v1_9.json `
  data/model_parameters_demo_1.1.0.json `
  --output work/audits/demo-1.1.0-tempo-policy.json
```

该工具不做随机模拟，而是列出早期落后、阈值以下、末节打平、末节落后和末节领先
五种情境的有效节奏、三档概率与期望球权耗时，并执行四项确定性门禁。

分布审计还会从正式事件账本逐球权重建实时比分，并输出：

- `late_game_trailing_mean_observed_seconds`
- `late_game_neutral_mean_observed_seconds`
- `late_game_leading_mean_observed_seconds`
- 三类情境各自的样本球权数

每节最后一个被截断到零的球权不进入耗时均值，避免把剩余时钟误当作完整抽样耗时。

## 反事实证据

v1.8 静态节奏与 v1.9 情境节奏使用共同种子、每格 300 场。三个独立种子汇总：

| 指标 | v1.9 - v1.8 |
| --- | ---: |
| 末节落后球权耗时 | `-0.5584` 秒 |
| 末节领先球权耗时 | `+0.4879` 秒 |
| 末节中性球权耗时 | `+0.0016` 秒 |
| 全场平均球队回合 | 约 `0.0000` |
| 每百回合得分 | `-0.0017` |
| 投篮命中率 | `-0.000006` |

六项方向及隔离门禁在 3/3 个种子上全部通过。证据入口：

- `experiments/matrices/demo-1.1.0-late-game-tempo.json`
- `experiments/contrasts/demo-1.1.0-late-game-tempo-v1.json`
- `work/contrasts/demo-1.1.0-late-game-tempo-robustness.json`
- `experiments/model-audit-demo-1.1.0.json`

## 当前边界

这还不是完整的末节教练 AI。暂停、故意犯规、两回合比赛、是否抢两次进攻、领先方
避免失误以及压哨出手质量都尚未建模。下一步应先增加“末节策略状态机”的领域契约，
再分别接入犯规和进攻选择；不能把所有末节行为压成一个节奏评分。
