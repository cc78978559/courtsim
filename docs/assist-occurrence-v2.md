# 传球者影响助攻发生 v2

## 结构结论

`demo-v1.7` 将助攻节点拆成两个条件步骤：

```text
终结创造模式
→ 潜在助攻者候选分布
→ 候选组织能力与进攻决策的加权期望
→ 是否形成助攻
→ 若形成助攻，抽取实际助攻者
```

旧结构只在最后一步使用球员能力，因此球员可以改变“助攻记给谁”，不能改变全队
助攻率。新结构继续使用概率状态机，不引入连续坐标或逐帧传球模拟。

发生概率在原创造模式基础 logit 上加入：

```text
occurrence_logit_intercept
+ occurrence_playmaking_coefficient * E[潜在传球者组织能力 z]
+ occurrence_decision_coefficient * E[潜在传球者进攻决策 z]
```

首版参数为 `-0.30 / 0.30 / 0.15`。负截距用于把平衡阵容锚定在既有联盟助攻
区间，两个正系数表达球员差异。

## 差分证据

200 场/cell、共同种子、固定基准对手：

- 平衡阵容从 v0.8 到 v0.9：总体助攻/命中约 `+0.0147`；
- 旧结构的内线中枢响应：主队助攻/命中约 `-0.0027`，接近零；
- 新结构的内线中枢响应：相对 v0.9 平衡阵容约 `+0.0492`；
- 同一内线中枢从旧结构升级：约 `+0.0655`；
- 得分、命中率和三分出手结构逐位不变。

三轮独立种子中，11 项方向和隔离门禁全部 `3/3`。新结构内线中枢响应均值
`+0.0486`，观测区间约 `0.0480..0.0492`。

## 冻结结果

正式种子 `20260728`、100 场、19,200 个球队球权：

- 助攻/命中：`0.663259`；
- NBA 核心目标：10/10；
- NBA 罚球目标：3/3；
- 回归门禁：25/25；
- audit SHA-256：
  `0f9dffea0c57c4eebbd75da7b30c74371c32f753b80acaaeb581b798cd9189e8`；
- games SHA-256：
  `194fcc2d55fb9afe4064b77d81347ec39ef0aae4c1ba6a3c705b7f7d5f223c80`。

与同种子的 v0.8 球队分侧审计比较，只有总体、主队和客队三项助攻率发生变化；
其余审计指标完全相同。

100 场、4 worker、`aggregate-only` 三次性能基准中位数约 `25.24 games/s`，与
v0.8 的 `25.40 games/s` 接近；首轮观测不足以声称性能提升或退化。

## 产物

- `data/model_schema_demo_v1_7.json`
- `data/model_parameters_demo_0.9.0.json`
- `data/baselines/model-audit-demo-0.9.0.json`
- `experiments/model-audit-demo-0.9.0.json`
- `experiments/model-audit-demo-0.9.0-regression-gates.json`
- `experiments/calibration/assist-occurrence-v1.json`
- `experiments/matrices/demo-0.9.0-assist-occurrence-effects.json`
- `experiments/contrasts/demo-0.9.0-assist-occurrence-v1.json`
