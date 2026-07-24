# 非投篮犯规与球队 Bonus

`demo-v1.6` 在既有领域事实、序列化、统计归属和比赛状态边界上启用了参数化概率
节点。`demo-v1.5` 及更早参数仍完全跳过该节点和新增随机槽。

## 领域事实

`NonShootingFoulSegmentResult` 保存：

- 进攻计划与防守 coverage；
- 被犯规球员；
- 犯规球员；
- 零次或两次罚球结果；
- 末罚不中时的篮板。

被犯规球员在首版固定为当前计划持球人。零次罚球表示尚未进入 bonus，进攻方保留
球权并进入下一行动片段；两次罚球表示 bonus。末罚命中或防守篮板结束球权，进攻
篮板继续球权。

个人犯规、罚球、罚球得分和篮板全部由正式片段事件归属，不在比赛层另造统计。

## 比赛状态

球队犯规由比赛层按防守球队、按节维护：

```text
period start -> both team foul counts = 0
shooting foul -> defending team +1
non-shooting foul -> defending team +1
current count + new foul >= bonus threshold -> two free throws
```

状态通过 `defense_team_fouls` 和 `bonus_foul_threshold` 传入球权采样器。球权层只
决定本次犯规是否罚球，不拥有跨球权累计。

首版不实现 NBA 最后两分钟的独立“两次犯规即 penalty”规则，也不实现进攻犯规、
技术犯规、恶意犯规或个人六犯离场。

## 兼容性

- 事件序列化从版本3升到4，读取器继续兼容版本1～3；
- `RandomSlot.NON_SHOOTING_FOUL=22`；
- `RandomSlot.NON_SHOOTING_FOULER=23`；
- 旧参数 policy 返回 `None`，采样器完全跳过两个新随机槽；
- 旧参数的事件结果、随机地址和 Decision Trace 不变。

## Demo v1.6 数值节点

基础概率按 `BALL_SCREEN`、`ISOLATION`、`OFF_BALL_ACTION` 分开。logit 修正只读取：

- 当前交互的 `ball_pressure`；
- 持球人的 `foul_drawing` 与 `contact_seek`；
- 与持球人相关的主要及协防球员平均 `foul_discipline`。

犯规人 hazard 只在这些相关防守人中抽样，并让较高的 `foul_discipline` 降低犯规
权重；交互数据没有相关防守人时才退回完整防守阵容。分布审计公开
`non_shooting_foul_rate`、`bonus_non_shooting_foul_rate` 和
`defensive_foul_rate`。

冻结数值、候选矩阵和多种子证据见 `common-foul-calibration-v1.md`。当前证据只支持
总体事件量，不支持宣称个体球员犯规分布已经拟真。
