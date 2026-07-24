# 阶段 3：PlayerProfile v1

`PlayerProfile v1` 是不随阵容改变的静态球员档案。它包含20项能力、17个倾向数值、体型级别和仅供展示的名义角色标签。

它刻意不包含：

```text
overall_rating
offense_rating
defense_rating
```

任何综合评价都只能是展示信息或离线模拟结果，不能回流进比赛概率。

## 20项能力

```text
perimeter_creation
post_creation
ball_security
playmaking
off_ball_movement
screen_setting
rim_finishing
midrange_shooting
three_point_shooting
free_throw_shooting
foul_drawing
point_of_attack_defense
post_defense
rim_protection
steal_skill
foul_discipline
offensive_rebounding
defensive_rebounding
offensive_decision
defensive_awareness
```

全部使用0～100整数。50始终表示固定参考联盟的中性水平，不根据当前存档重新归一化。

阶段 3 已建立完整属性作用账本。每项能力恰有一个主要所有者节点，并可声明有界的角色/侦察次级用途和禁止节点。

当前概率模型尚未实现背身、罚球和犯规，因此以下能力在比赛节点编译中 dormant：

```text
post_creation
post_defense
free_throw_shooting
foul_drawing
foul_discipline
```

阶段 6 已从动态角色公式中移除这些 dormant 字段，避免计划与参与者选择产生间接效果。只有对应机制升级并修改结构契约后，才能重新启用它们。

## 17个倾向数值

```text
offensive_involvement                         1
play_role_mix(handler/post/spot_up/cutter/screener) 5
shoot_vs_pass                                 1
shot_zone_mix(rim/midrange/three)             3
pass_risk                                     1
contact_seek                                  1
offensive_rebound_commitment                  1
defensive_rebound_commitment                  1
steal_gamble                                  1
help_aggression                               1
block_chase                                   1
```

倾向只控制选择、参与和风险偏好，不直接提高执行成功率。`contact_seek` 与 `play_role_mix.post` 当前 dormant。

## 固定映射

能力通过固定锚点线性插值为潜在标准分：

```text
rating: 0, 20, 35, 50, 65, 80, 95, 100
z:     -3,-1.8,-0.9, 0, 0.9,1.8,2.6,3
```

标量倾向：

```text
clip((rating - 50) / 18, -2.75, 2.75)
```

混合倾向先减去组内平均，再除以15并裁剪到 `[-3,3]`。因此三个区域全部填80与全部填40具有相同的相对区域偏好。

## 节点隔离

比赛模块不应接收完整 `PlayerProfile`。调用：

```python
compile_player_features_for_node(profile, node)
```

只会得到该节点允许读取的 `NodePlayerFeatures`。例如：

- `shot.make.three` 只能得到三分投射标准分
- `shot.zone.select` 只能得到区域倾向偏置，得不到投射能力
- 名义角色标签永远不会出现在编译结果中
- dormant 特征不会进入任何当前比赛节点

## 动态角色

五人阵容可确定性推导：

- 持球点
- 掩护者
- 弱侧射手
- 护框者
- 进攻篮板者
- 防守篮板者
- 持球点主防人

每个角色保存连续评分、稳定排名和温度为0.75的 softmax 自然份额。平分按球员ID升序；没有正分护框者时，`primary_rim_protector_id=None`；第二持球点不满足份额和评分门槛时显式标记阵容缺少第二创造点。

名义角色标签只用于UI和检索，不参与动态角色计算。阶段 6 起，动态角色自然份额用于计划参与者选择；它仍不直接修改投篮、失误或篮板执行结果。
