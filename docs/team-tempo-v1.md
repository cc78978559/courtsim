# 球队节奏 v1

## 结论

`demo-v1.8` 将节奏实现为球队级策略，不属于球员能力，也不修改单个球权内部的
进攻计划、投篮、失误或命中概率。人工输入 `tempo` 使用 `0..100`，中性值为 50。

旧结构版本继续使用 `GameClockConfig.possession_seconds` 的固定耗时；只有
`demo-v1.8` 读取 `possession_duration` 节点并抽样 `SHORT`、`STANDARD`、`LONG`
三档耗时。当前数值分别为 12、15、18 秒，基础概率为 0.2、0.6、0.2。

## 概率模型

运行时先把 `tempo` 映射为中心化倾向，再用 `tempo_coefficient=0.45` 对三档权重
作对称调整：

```text
SHORT    base * exp(+tempo_bias)
STANDARD base
LONG     base * exp(-tempo_bias)
```

抽样使用追加的 `RandomSlot.POSSESSION_DURATION = 24`。既有随机槽没有重排；
旧版本不访问新随机槽，因此旧参数的事件流语义保持不变。

每节末剩余时间不足时，球权耗时截断到零。正式账本仍只保存
`clock_start_seconds` 与 `clock_end_seconds`，验证器根据 v1.8 参数允许的耗时集合
检查每次递减；旧版本仍执行固定耗时的严格检查。

## 审计结果

共同种子、每格 200 场的首轮矩阵：

| 策略 | 平均球队回合 |
| --- | ---: |
| v0.9 固定 15 秒 | 96.00 |
| v1.0 中性 50 | 96.72 |
| v1.0 双方快 90 | 104.83 |
| v1.0 双方慢 10 | 89.85 |

三组独立种子的配对反事实结果：

- 快节奏相对中性，回合增量均值 `+8.0475`，范围 `+8.015..+8.105`；
- 慢节奏相对中性，回合增量均值约 `-6.896`；
- 中性相对旧固定时钟，每百回合得分增量均值 `-0.0328`；
- 快节奏的每百回合得分增量范围 `-0.0112..+0.2668`；
- 9 项方向与隔离门禁在 3/3 个种子上全部通过。

证据入口：

- 矩阵：`experiments/matrices/demo-1.0.0-team-tempo.json`
- 对照门禁：`experiments/contrasts/demo-1.0.0-team-tempo-v1.json`
- 多种子报告：`work/contrasts/demo-1.0.0-team-tempo-robustness.json`
- 正式审计：`experiments/model-audit-demo-1.0.0.json`

## 当前边界

该节点表达的是球队希望以多快速度完成一个球权，不是实时比赛管理。比分、剩余时间、
犯规麻烦、暂停、末节策略和对手压节奏尚未反馈到 `tempo`。后续如增加动态节奏，
应在球队策略层组合上下文修正，不应把这些状态塞进球员评分。
