# NBA 球员数据与身份映射 v1

本流程面向免费的个人研究用途。原始 Parquet 只保存在被 Git 忽略的
`.cache/nba-data`，CourtSim 仓库只保存来源清单、SHA-256 和处理代码。
PyArrow 是本地数据工具的可选依赖，不进入模拟运行时：

```powershell
.\tools.cmd bootstrap-data
```

## 2024-25 box-score 与分钟

清单 `experiments/nba-data/hoopr-player-box-2024-25.json` 固定了
SportsDataverse hoopR 的 `player_box_2025.parquet`。构建时仅投影实际需要的列，
按 65,536 行批次读取，并在本机按球队、ESPN 球员 ID 和姓名复合分组：

```powershell
.\tools.cmd nba-data sync `
  experiments/nba-data/hoopr-player-box-2024-25.json
.\tools.cmd nba-data build `
  experiments/nba-data/hoopr-player-box-2024-25.json `
  work/nba-2024-25-player-box-summary.json
```

常规赛过滤使用 `season_type=2` 与 30 支 NBA 球队 ID 白名单，排除混在同一类型
中的 All-Star 队。出赛场次使用 `did_not_play=false`，不能使用上游 `active` 字段；
真实烟测表明 `active` 并不表示球员是否出赛。

## ESPN ID 到 NBA Stats ID

清单 `experiments/nba-data/hoopr-player-crosswalk-2026.json` 固定上游当前提供的
2025-26 crosswalk。身份构建只按 ESPN ID 连接，不使用姓名回退：

```powershell
.\tools.cmd nba-data sync `
  experiments/nba-data/hoopr-player-crosswalk-2026.json
.\tools.cmd nba-data build `
  experiments/nba-data/hoopr-player-crosswalk-2026.json `
  work/nba-player-crosswalk-2026-summary.json
.\tools.cmd nba-data build-player-identity `
  work/nba-2024-25-player-box-summary.json `
  work/nba-player-crosswalk-2026-summary.json `
  work/nba-player-identity-2024-25.json
```

`nba-player-identity-v1` 保存两份输入摘要和原始文件的哈希、ESPN/NBA ID、匹配方法、
置信度、球队、场次和分钟。`courtsim_player_id` 暂为 `null`，直到现实阵容导入器显式
分配模拟 ID。未匹配球员保留在 `unmatched`，不会通过同名猜测自动补齐。

正式提升门槛默认为球员覆盖率至少 90%、分钟覆盖率至少 95%、单条匹配置信度至少
90%。目前上游只发布 2025-26 当前 crosswalk，用它映射 2024-25 box-score 的真实烟测
覆盖率为 311/580（53.62%），分钟覆盖率为 67.09%，所以产物会正确标记
`promotion.ready=false`。它可以用于开发和缺口审计，不能作为正式球员校准输入。
