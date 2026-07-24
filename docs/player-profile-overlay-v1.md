# 球员档案覆盖与单因素敏感性 v1

球员档案覆盖工具用于从完整五人阵容生成只改变少量评分叶子的实验夹具。它避免为
每个反事实实验复制和人工维护整份约7 KB阵容 JSON。

## Overlay 契约

```json
{
  "format_version": 1,
  "kind": "courtsim-player-lineup-overlay",
  "overlay_id": "example-overlay-v1",
  "lineup_id": "example-derived-lineup-v1",
  "notes": "Why this controlled fixture exists.",
  "overrides": [
    {
      "player_id": 2,
      "path": ["abilities", "three_point_shooting"],
      "value": 20
    }
  ]
}
```

允许修改：

- `abilities.<rating>`；
- `tendencies.<scalar-rating>`；
- `tendencies.play_role_mix.<rating>`；
- `tendencies.shot_zone_mix.<rating>`。

值必须是 `0..100` 整数。禁止修改球员ID、姓名、体型、名义角色标签和任何对象；
同一球员的同一路径不能重复。基础文件必须是包含恰好五名不同球员的正式 lineup，
不能是单球员模板。

## 生成与验证

```powershell
.\tools.ps1 profile-overlay `
  examples/calibration_lineup_v1.json `
  experiments/profile-overlays/player2-three-ability-low-v1.json `
  work/profiles/player2-three-ability-low-v1.json

.\tools.ps1 verify `
  work/profiles/player2-three-ability-low-v1.json.manifest.json
```

生成器先用正式 PlayerProfile 加载器验证基础阵容和派生阵容，然后写出：

```text
<output>.json
<output>.json.manifest.json
```

manifest 使用全项目统一的 `inputs[]/outputs[]` 哈希清单，绑定基础阵容、overlay 和
派生阵容，可由通用 `verify` 命令检查。已有输出或 manifest 不会被静默覆盖。

## 首个单因素实验

`demo-0.7.0-single-factor-three.json` 使用共同 `seed_group` 比较：

1. 原始平衡阵容；
2. 只把2号球员 `shot_zone_mix.three` 从85降到10；
3. 只把2号球员 `three_point_shooting` 从80降到20。

每个复现200场，共3个独立配对种子。结果：

| 单因素修改 | 主要指标平均 delta | 次级指标平均 delta |
| --- | ---: | ---: |
| 三分倾向降低 | 三分区域占比 `-0.222` | 2号使用率 `-0.0001` |
| 三分能力降低 | 三分命中率 `-0.066` | 三分占比 `-0.026`、2号使用率 `-0.112` |

两组6项方向门禁均为 `3/3` 通过。

能力降低引起的使用率变化不是投篮区域选择节点直接读取命中能力，而是能力参与动态
弱侧射手评分和后续参与者选择的允许次级路径。节点隔离应由
`compile_player_features_for_node` 的单元测试保证；端到端对比负责冻结最终可观察
效应，不能把两者混为同一个断言。

这些合成测试证明字段作用方向和主要/次级路径可观察，不代表属性刻度已经映射到
真实NBA球员差异。
