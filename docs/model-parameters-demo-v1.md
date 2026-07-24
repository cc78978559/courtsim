# 阶段 2：Demo v1 参数契约

阶段 2 把模型分成两个独立、可哈希的版本化文件：

- `data/model_schema_demo_v1_3.json`：结构契约
- `data/model_parameters_demo_0.4.0.json`：数值参数

当前数值是未经校准的结构启动值，只用于证明参数可以安全驱动完整行动段。它们不能解释为已经达到 NBA 统计拟真度。

## 结构契约

结构 schema 冻结：

- 节点名称和类型
- 节点类别全集
- 每个节点允许读取的特征
- 固定特征载荷
- dormant 特征
- RNG schema 版本

Python 内核保存同一份预期契约，并在加载时反向核对 JSON。仅仅修改 schema 文件并不能让 `overall_rating` 或其他未注册特征进入节点；这种修改会直接加载失败。

当前激活节点：

```text
terminal_competing_risk
finisher_route
shot_zone
contest_gate
shot_make
rebound_side
```

终结球员路线内选择使用候选 `availability × 1.0`。这个 `1.0` 是结构 schema 中的固定载荷，不是隐藏在编译器中的自由参数。

第一阶段 dormant 特征包括背身、罚球、造犯规、犯规纪律、背身角色倾向和主动找对抗倾向；参数文件不得激活它们。

## 数值参数

数值文件当前包含：

- 三种进攻计划的竞争终止基础率
- `ball_pressure` 和 `pass_release` 的居中 softmax 系数
- 各计划的终结路线基础率
- 每个合法 `PlayFamily × FinisherRoute` 的区域率
- 各区域封盖/重度干扰/普通投篮基础率
- 各区域普通对抗命中率与重度干扰 logit 偏移
- 中性前场篮板率
- 最大行动段安全上限

所有 softmax 特征权重必须覆盖完整类别并严格居中；概率向量必须类别完全匹配、每项处于 `(0,1)` 且总和为 1。普通系数绝对值不能越过 2.0，Demo v1 最多允许 30 个可训练标量。

当前参数全部标记为不可训练。正式开放某个参数训练前，还需要为它登记隔离识别实验。

### 区域率适配说明

设计审计提供的是旧语义下的组合路线率，例如挡拆掩护者和弱侧球员。转换到冻结后的路线时采用：

- `SCREENER_ROLL`：在合法的 `RIM/MIDRANGE` 内重新归一化
- `SCREENER_POP`：在合法的 `MIDRANGE/THREE` 内重新归一化
- `HELP_RELEASE`：在合法的 `MIDRANGE/THREE` 内重新归一化
- 无球预定目标：删除首版非法的篮下区域后重新归一化

这些仍是启动假设，必须通过节点级目标校准，而不是当作真实联盟结论。

## 编译策略

`CompiledParameterPolicy` 在启动时接收已经验证的 `ModelParameters`，把参数转换成 `SegmentProbabilityPolicy`：

- 终止节点：基础率乘以居中特征 logit 效应
- 路线节点：按计划读取合法路线率
- 路线内球员：按稳定球员 ID 排序，对 availability 做 softmax
- 区域节点：只读取合法的计划/路线区域表
- 对抗节点：按区域读取基础率；多个封盖者平分 `BLOCK` 类概率
- 命中节点：区域基础 logit 加重度干扰偏移
- 篮板节点：先判球队归属，再在对应阵容内选人

`CompiledParameterPolicy` 保留中性等权行为；阶段 4 的
`PlayerAwareCompiledPolicy` 使用版本化的球员抢断与篮板 hazard，并确保球队事件与个人归属共享同一组权重。

## 稳定哈希

schema 与参数分别计算 SHA-256。参数哈希会：

- 递归排序对象键
- 浮点数舍入到 9 位
- 使用紧凑 JSON
- 禁止 NaN 和 Infinity
- 排除 `parameter_hash`、`created_at_utc` 和 `notes`

当前 Golden：

```text
schema_hash:
8fc2f9243e7f83711549ad67cc51435b8d078524d7221a0ec41e2d8f3c675ff0

parameter_hash:
c3592432913e940005ff69449c31e2e30a23355f1986e1d5a18a214daff22d38
```

PlayerProfile v1、动态角色驱动的计划参与者选择、条件防守响应和结果节点特征均已接入。高层入口会自动生成攻防交互状态；对位关系仍由调用方提供。
