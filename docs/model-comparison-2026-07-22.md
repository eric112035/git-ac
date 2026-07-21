# Spark／Luna 大型 staged diff 初步比較（2026-07-22）

## 測試條件

- Codex CLI：`0.144.6`
- 模型：`gpt-5.3-codex-spark`、`gpt-5.6-luna`
- Fixture：單一 `large_rules.py`，184,750 UTF-8 bytes
- Staged diff：185,258 bytes
- 必要標記：`FACT_CODEX_LARGE_00` 至 `FACT_CODEX_LARGE_11`，共 12 個
- Prompt budget：每次最多 48,000 UTF-8 bytes
- 模式：`-c -p`，不 commit、不修改 index
- 每個模型各執行 1 次；兩者使用相同 deterministic fixture 與 staged tree `e16114fc7e67e89cb9878e9937303421341772be`

Trace 僅記錄 backend、model、stage、prompt/output bytes、`FACT_` 標記、耗時及成功狀態；不保存 prompt、diff 或完整模型輸出。

## 結果

| 指標 | Spark | Luna |
| --- | ---: | ---: |
| 成功 | 是 | 是 |
| 總耗時 | 34.296 秒 | 41.096 秒 |
| 呼叫階段 | 4 map + 1 final | 4 map + 1 final |
| 最大 prompt | 47,345 bytes | 47,345 bytes |
| map 必要標記涵蓋 | 12/12 | 12/12 |
| final literal 標記涵蓋 | 2/12 | 0/12 |
| final 範圍正規化涵蓋 | 12/12 | 0/12 |
| staged snapshot 未變 | 是 | 是 |
| 建立 commit | 否 | 否 |

Spark 訊息：

```text
feat(large_rules): 新增 shipping-inventory-payment-audit 大量規則識別常量

新增 `large_rules.py` 中多筆 `rule_` 常量與對應 `shipping-inventory-payment-audit-<id>-...` 識別字串，並保留 `FACT_CODEX_LARGE_00` 到 `FACT_CODEX_LARGE_11` 的標記，僅擴充資料內容未改邏輯。
```

Luna 訊息：

```text
feat(rules): 新增大型規則資料與規則字串常數
```

## 判讀

- 兩個模型都能在 production 48,000-byte budget 下完成真實 chunk 摘要與最終 commit message，且格式驗證通過。
- Spark 在此案例比 Luna 快約 16.5%，並保留標記範圍與「只擴充資料、未改邏輯」等重要資訊。
- Luna 的 map 摘要完整看過 12 個標記，但 final message 過度壓縮，沒有保留任何驗收標記或規則範圍。
- 184 KB 案例的四份 map 摘要可直接放入 final prompt，因此沒有額外 reduce 階段；顯式 recursive reduce 另由 1 MB production-budget 離線案例驗證至少兩層。
- 本結果支持暫時維持 Spark 為預設，但只有單一案例、每個模型各一次，不能取代 20 案、各 3 次的正式發行評測。

## Luna 相容性紀錄

最初使用 Codex CLI `0.136.0` 時，服務回覆 `gpt-5.6-luna` 需要新版 Codex。CLI 升級到 `0.144.6` 後，model catalog 同時列出 Luna 與 Spark，Luna 測試成功。舊版 CLI 的失敗結果未納入上表比較。
