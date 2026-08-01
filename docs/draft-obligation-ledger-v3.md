# Draft obligation / freeze ledger v3

`draft-obligation-ledger-v3` 是现有 `draft-asset-v2` 所有权账本之上的只读约束层。
它不复制或改写选秀权所有权，而是记录：

- 每个已送出的选秀权义务、债务队、债权队和原始 asset ID；
- 最早/最晚可能兑现年份与可能轮次；
- 因未决首轮义务而暂时禁止再次交易的本队首轮签；
- 固定的七年 Stepien 审计窗口和源 asset ledger SHA-256。

构建器对保护顺延采用保守边界：首轮义务可能在 `earliest_year..latest_year` 任一年
兑现，因此债务队仍持有的该窗口首轮和每个可能兑现年份后的下一年首轮都会被冻结。
只有显式结算并重建 v3 账本才能解除冻结。

只读 CLI 不改变两个输入文件：

```powershell
.\tools.cmd draft-obligation-audit `
  work/draft-obligations-v3.json `
  work/draft-assets.json `
  --output work/draft-obligation-audit.json
```

审计验证源哈希、asset 引用、冻结身份、完整七年本队首轮覆盖，以及不同义务之间的
最坏情况连续首轮风险。单一保护义务在相邻年份的互斥兑现可能性不会被误报为两次送出；
只有两个不同义务能落在相邻年份时才报告 `stepien_risk_pairs`。非 ready 状态返回退出码 6。
