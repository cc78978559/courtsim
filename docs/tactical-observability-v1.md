# 战术可观测性 v1

分布审计现在同时记录全联盟和逐队的三层进攻观测：

- `route_shares`：终结路线，例如持球人自攻、顺下、外弹、弱侧释放；
- `creation_mode_shares`：自主持球、挡拆伙伴喂球、定点喂球、无球移动喂球；
- `tactical_action_shares`：面向实验的具体战术词汇。

新增 `TacticalAction` 是 append-only 稳定枚举：`BALL_SCREEN_KEEP`、
`BALL_SCREEN_ROLL`、`BALL_SCREEN_POP`、`BALL_SCREEN_KICKOUT`、
`ISOLATION_ATTACK`、`ISOLATION_KICKOUT`、`PINDOWN`、`BACKDOOR_CUT` 和
`OFF_BALL_BAILOUT`。

这些词汇由规范 `plan + route + screen_setter` 因果结构推导，而不是从结果分数反推。
例如同为 `DESIGNED_OFF_BALL_TARGET`，存在掩护人时记为 `PINDOWN`，没有掩护人时记为
`BACKDOOR_CUT`。因此实验可以区分真实战术结构，不能把两个标签任意互换。

本版本只增加白盒观测和命名，不修改任何抽样概率或旧参数。旧 v1 audit 没有三组扩展字段时
仍能加载；新 audit 必须一次性提供完整的 route、creation 和 tactical-action 三组指标，
避免半升级产物进入比较门禁。
