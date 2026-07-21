# 本機 oMLX 大型 staged diff 驗收（2026-07-22）

## 測試條件

- `aitext`／aichat：`0.30.0`
- 實際 oMLX model slug：wrapper 的安全版本介面未提供，尚待補記
- Fixture：單一 `large_rules.py`，154,444 UTF-8 bytes
- Staged diff：154,892 bytes
- 必要標記：`FACT_CODEX_LARGE_00` 至 `FACT_CODEX_LARGE_11`
- Prompt budget：每次最多 48,000 UTF-8 bytes
- 模式：`-p`，不 commit、不修改 index

Trace 僅記錄 backend、stage、prompt/output bytes、`FACT_` 標記、耗時及成功狀態；不保存 prompt、diff 或完整模型輸出。

## 結果

- 成功完成 4 個 map chunks 與 1 個 final 呼叫。
- 最大 prompt 為 47,345 bytes。
- 總耗時 100.331 秒；模型呼叫合計 100.193 秒。
- final literal 標記涵蓋 2/12；將 `00 至 11` 範圍展開後涵蓋 12/12。
- 執行前後 staged tree 均為 `787758284507ce343828dcdaff0e9ed594a031bd`。
- 沒有建立 commit。

產生的訊息：

```text
feat(large_rules): 新增一系列 shipping-inventory-payment-audit 相關規則定義

新增 `large_rules.py` 檔案，定義 `rule_0000` 至 `rule_0152` 規則變數，並包含 `FACT_CODEX_LARGE_00` 至 `FACT_CODEX_LARGE_11` 等事實標記。
```

## 判讀

- 本機 `aitext`／oMLX 能成功處理超過 150 KB 的 staged diff，不需要人工拆分 add 或 commit。
- map 摘要與 final 訊息都能通過 orchestration；最終訊息合法且保留完整標記範圍。
- 此案例的四份 map 摘要合計小於 48 KB，因此直接進入 final，沒有額外 recursive reduce；production-budget 的兩層 recursive reduce 已由超過 1 MB 的離線 E2E 案例覆蓋。
