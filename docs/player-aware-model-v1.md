# 阶段 4：球员感知概率模型

阶段 4 将 `PlayerProfile v1` 的首批激活特征接入行动段，同时保持阶段 0 的规范结果和阶段 1 的 RandomFrame 不变。

参数契约升级为：

```text
schema_version:    demo-v1.3
parameter_version: demo-0.4.0
```

对应文件：

```text
data/model_schema_demo_v1_3.json
data/model_parameters_demo_0.4.0.json
```

当前仍是未经联盟数据校准的结构启动参数。

## 一次计算、下游复用

### 抢断

每个符合资格的防守者只生成一次 `PlayerHazard`：

```text
0.50 × steal_skill_z
+ 0.30 × steal_gamble_bias
```

同一 `StealHazards` 同时提供：

- 终止竞争模型中的 `team_steal_pressure`
- 抢断失误发生后的具体抢断者权重

不存在第二次独立抢断抽样或重新读取抢断属性。

### 篮板

一次投失只生成一份 `ReboundHazards`，包含攻守双方十名球员：

```text
进攻：
0.45 × offensive_rebounding_z
+ 0.30 × offensive_rebound_commitment_bias
+ event context

防守：
0.45 × defensive_rebounding_z
+ 0.30 × defensive_rebound_commitment_bias
+ event context
```

同一组权重先决定 `REBOUND_SIDE`，再在已选球队内决定 `REBOUNDER`。球员能力和倾向不会在第二步重新加入。

中性五对五环境用防守权重因子3.0维持25%的启动前场篮板率。投篮者、封盖者和封盖投失只通过显式事件偏移改变位置。

## 已接入的节点

### 终止竞争

在原有 `ball_pressure` 与 `pass_release` 之外加入：

- 控球保护：降低两个 `LOST_BALL`
- 进攻决策：降低坏传球及违例
- 传球风险：提高坏传球风险
- 已编译的球队抢断压力：提高两个抢断失误类别

所有类别系数均在参数文件中中心化。

### 投篮区域

区域倾向组内中心化后，以固定载荷0.75进入区域 softmax。对应区域投篮能力完全不可见，因此提高三分能力不会增加三分出手概率。

### 封盖与干扰

封盖候选的护框能力和追帽倾向只进入 `contest_gate`：

- 改变 `BLOCK / HEAVY_CONTEST / NORMAL`
- 多名封盖者仍在同一 contest 节点内竞争归属
- 后续命中节点只接收 `ContestLevel`，不再读取护框或追帽

### 投篮命中

命中节点只读取与区域对应的能力：

```text
RIM      → rim_finishing × 0.28
MIDRANGE → midrange_shooting × 0.24
THREE    → three_point_shooting × 0.22
```

区域能力以标准分进入 logit；不会回流到终结者或区域选择。

## 尚未接入

- 动态角色驱动的计划、发起者与搭档选择
- 犯规、罚球、背身、转换进攻和体力

阶段 5 已增加独立的确定性交互编译器。调用者仍需提供计划、Coverage 和完整对位，但不再需要手工构造 `InteractionState`。
