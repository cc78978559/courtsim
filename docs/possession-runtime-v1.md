# Possession Runtime v1

阶段 7 将一个或多个 `ActionSegmentResult` 组合成完整球权。状态机只有一条继续边：

```text
行动片段
  ├─ 命中投篮           -> MADE_SHOT
  ├─ 失误               -> TURNOVER
  ├─ 防守篮板           -> DEFENSIVE_REBOUND
  └─ 进攻篮板           -> 下一行动片段
```

达到安全上限时返回 `SEGMENT_LIMIT`。它表示模拟被截断，不会伪造失误、防守篮板或已完成球权。

## 领域契约

`PossessionEndReason` 采用 append-only 编号：

```text
MADE_SHOT=0
TURNOVER=1
DEFENSIVE_REBOUND=2
SEGMENT_LIMIT=3
```

`PossessionResult` 保存：

- 按因果顺序排列的非空片段；
- 明确的终止原因；
- `completed` 派生状态。

除最后一个片段外，所有片段必须以进攻篮板结束。自然终止原因必须与最后一个片段一致；`SEGMENT_LIMIT` 的最后一个片段必须仍由进攻方保有球权。

## 随机地址

`sample_possession()` 接收一个起始 `RandomFrame`。每次进攻篮板后只增加：

```text
segment_index += 1
```

主种子、场景、复现实验、比赛和球权编号保持不变。因此同一球权的每个行动都具有独立且可直接重建的随机地址。

## 统计账本

`attribute_possession()` 不重新解释篮球事件，只累加每个 canonical segment 的 `attribute_segment()` 结果：

- 得分为各片段 `score_delta` 之和；
- 球员统计按 `(player_id, StatCode)` 合并；
- 自然结束的球权记 `possession_delta=1`；
- `SEGMENT_LIMIT` 记 `possession_delta=0`。

这样安全阀不会污染节奏、失误率或防守篮板率。

## 序列化

`possession_result_to_json()` 和 `possession_result_from_json()` 使用严格字段集合，并验证片段连续性及终止原因。设置阶段和概率 trace 暂不进入 canonical 结果；它们保留在运行时的 `PossessionSample.segment_samples` 中。

## 当前边界

本阶段没有引入比赛时钟、节次、罚球、犯规、换人或双方轮换。下一层比赛运行时应消费已经完成的球权，并显式处理攻防交换；截断球权应作为异常样本进入审计，而不能静默继续比赛。
