# 故意犯规正式执行 v1

`demo-v1.11 / demo-1.3.0` 将末节策略状态中的一部分
`DEFENSE_INTENTIONAL_FOUL` 机会提升为正式事件。

> 后续状态：`demo-v1.12 / demo-1.4.0` 已补齐非 bonus 续接；
> 本文保留为 bonus-only 版本契约。参见 `intentional-foul-continuation-v1.md`。

## 执行边界

只有同时满足以下条件才正式执行：

1. 第四节最后 30 秒；
2. 当前进攻方领先 3～8 分；
3. 防守方本次犯规后达到 `bonus_foul_threshold`。

未达到 bonus 的机会仍只计入 `intentional_foul_opportunities`，不强行生成事件。
这是首版的有意限制：当前球权模型还没有“非 bonus 犯规后界外球重新发起进攻”的独立时钟阶段。

## 正式因果链

```text
末节状态机选择故意犯规
→ 正常选择进攻计划、持球人、coverage 和对位上下文
→ 按原有犯规 hazard 选择犯规人
→ 持球人执行两次 bonus 罚球
→ 末罚不中时按原有篮板 hazard 选择篮板人
→ 事件账本归属 PF、FTA、FTM、PTS、OREB/DREB
→ 比赛时钟固定消耗 3 秒
```

状态机决定“是否故意犯规”，因此不消耗普通
`NON_SHOOTING_FOUL` 决策随机槽；犯规人、罚球和篮板继续使用既有随机槽。
普通非投篮犯规与故意犯规共用同一结果构造函数，不存在第二套统计逻辑。

## 审计字段

- `intentional_foul_opportunities`：状态机识别出的全部机会；
- `intentional_fouls_committed`：满足 bonus 门槛并正式执行的次数；
- `intentional_foul_mean_observed_seconds`：正式事件平均耗时。

旧版审计文件缺少后两个字段时按零读取。

## 三种子初步验证

每个种子 100 场、4 workers、aggregate-only：

| 种子 | 机会 | 正式执行 | 平均耗时 |
| --- | ---: | ---: | ---: |
| 20260728 | 34 | 25 | 3.0 秒 |
| 20260729 | 34 | 26 | 3.0 秒 |
| 20260730 | 25 | 19 | 3.0 秒 |

相对 `demo-1.2.0` shadow 基线，三种子的罚球率分别增加
`0.00295 / 0.00317 / 0.00198`，防守犯规率分别增加
`0.00115 / 0.00131 / 0.00078`。方向一致，但这只是结构冒烟验证，
尚不能作为正式现实性校准或版本冻结依据。

证据位于 `work/audits/demo-1.3.0-seed-*`；三个 manifest 均已通过哈希验证。

100 场、4 workers、3 次重复的 aggregate-only 性能门禁中位数为
`24.88 games/s`，最低 `24.09 games/s`，通过 `20 games/s` 门槛。
报告位于 `work/benchmarks/demo-1.3.0-intentional-foul.json/benchmark.json`。

## 可复现迁移

```powershell
.\tools.ps1 parameters-promote-intentional-foul `
  data/model_schema_demo_v1_11.json `
  data/model_parameters_demo_1.2.0.json `
  experiments/calibration/intentional-foul-execution-v1.json `
  work/model_parameters_demo_1.3.0.json
```

生成文件的语义参数哈希必须为：

```text
e3ba033d59a189d6926a8b47cdfb0eb4c7d8b24b68c37e1ba14d5d591692a804
```
