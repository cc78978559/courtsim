# Game Runtime v1

阶段 8 将完整球权组合成双队常规比赛：

```text
比赛
  -> 节次
    -> 球权
      -> 行动片段
        -> canonical result
```

首版只负责攻防交换、比分、固定球权耗时、节次边界和比赛级统计账本。

## 比赛时钟

`GameClockConfig` 包含：

```text
regulation_periods
period_seconds
possession_seconds
```

只要节内时钟大于 0，就允许发起一个完整球权。球权结算后执行：

```text
clock_end = max(0, clock_start - possession_seconds)
```

这是一种校准前的固定耗时模型。它不会在节末制造半个球权，也暂不表达抢投、压哨出手或前场发球。

时钟归零后进入下一节，但攻防交替顺序不会重置。

## 攻防交换

主队默认获得首个球权。每个自然完成的球权都会交换攻防方，包括：

- 命中投篮；
- 失误；
- 防守篮板。

进攻篮板仍在同一个 `PossessionResult` 内续打，不发生攻防交换。

主队进攻和客队进攻分别持有一套基础对位映射。Coverage 引发的换防和协防仍由 Interaction Compiler 处理。

## 比赛结束

`GameEndReason` 使用 append-only 编号：

```text
REGULATION=0
POSSESSION_TRUNCATED=1
```

最终节时钟归零且最后一个球权自然完成时，比赛以 `REGULATION` 结束。

如果任何球权触发 `SEGMENT_LIMIT`，比赛立即以 `POSSESSION_TRUNCATED` 结束。运行时不会交换攻防方或继续消耗后续球权，以免把异常样本混入正式比赛。

## 事件账本

`GameResult` 保存每个球权的：

- 全局连续球权编号；
- 节次；
- 起止时钟；
- 攻防球队；
- canonical `PossessionResult`。

比分和球员统计虽然作为查询缓存保存在结果中，但校验器会从所有行动片段重新计算并逐项比对。修改缓存比分、时钟、攻防顺序或统计都会导致验证失败。

## 随机地址

比赛运行时保持：

```text
master_seed
scenario_id
replicate_id
game_id
```

并为每个新球权递增 `possession_index`，在球权内部由阶段 7 递增 `segment_index`。同一输入的整场比赛可逐球权、逐行动复现。

## 序列化

`game_result_to_json()` 与 `game_result_from_json()` 提供严格字段集合和账本一致性验证。反序列化需要相同的 `GameClockConfig`，从而验证节次和时钟连续性。

## 当前边界

首版不包括：

- 加时赛；
- 犯规和罚球；
- 暂停与换人；
- 球权耗时概率分布；
- 最后两分钟策略；
- 开场跳球或交替球权规则。

因此平局可以在常规时间直接结束。下一阶段应优先做批量比赛与分布审计，而不是立刻添加上述规则：先确认基础得分、回合数、投篮结构和球员使用率是否处于合理范围。
