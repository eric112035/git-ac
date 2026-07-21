# 真實後端驗收摘要（2026-07-22）

## 環境

- Repository：`git-ac`
- Git：`2.52.0`
- Python：`3.12.9`（`uv run`）
- `aitext`／aichat：`0.30.0`
- Codex CLI：初次 commit 使用 `0.136.0`；大型模型比較使用 `0.144.6`
- Codex 模型：`gpt-5.3-codex-spark`、`gpt-5.6-luna`
- 時區：`Asia/Taipei`

`aitext` wrapper 的安全版本查詢不會回報實際 oMLX model slug，因此本次只記錄可取得的 aichat 版本；正式發行驗收仍需補上 oMLX 模型識別資訊。

## 實際 `git ac -p`：本機後端

- 測試資料：`git-ac` 初始專案的 10 個 staged 檔案。
- 執行介面：Git local alias `ac = !git-ac`，由暫存 `PATH` 指向 `src/git_ac.py`。
- 後端：真實 `aitext`／oMLX。
- 結果：成功，耗時約 138 秒。
- 產生標題：`feat: 初始化 git-ac 專案結構與測試環境`
- 驗證：HEAD 仍不存在；執行前後 staged tree 皆為 `e33eae2f0ba6b95aa2505b41e491c31de04f16fb`。

## 實際 `git ac -c`：Codex 後端

- 測試資料：與本機 preview 相同的 10 個 staged 檔案。
- 後端：官方 `codex exec`，model `gpt-5.3-codex-spark`。
- 結果：成功，建立且只建立一個 root commit，耗時約 16 秒。
- Commit：`6b31f2a378c8871e9ee1c042d4cc8c0176bc1145`
- 產生標題：`feat(core): 新增 git-ac staged snapshot commit message 產生器與本地/雲端測試架構`
- 驗證：commit tree、index tree 與執行前 staged tree 均為 `e33eae2f0ba6b95aa2505b41e491c31de04f16fb`；工作樹乾淨。

## 自動測試

- 指令：`uv run python -m unittest discover -s tests -v`
- 結果：20 個離線測試通過；1 個真實本機整合案例依預設跳過。
- 另以 `GIT_AC_RUN_LOCAL_INTEGRATION=1` 單獨執行真實本機小型 preview：1 個測試通過，耗時 17.789 秒。
- Codex commit 後再次執行離線測試：結果相同，耗時 2.198 秒。
- 150 KB 單檔案例：production 48,000-byte budget 下使用至少 4 個 map chunks，所有必要標記保留。
- 超過 1 MB 多檔案例：production 48,000-byte budget 下強制並通過至少兩層 recursive reduce；每個 prompt 均未超過預算。

## 真實 Spark／Luna 大型比較

- 兩個模型都以相同的 185,258-byte staged diff 完成 4 map + 1 final。
- 每個 prompt 最大 47,345 bytes；兩者 map 必要標記涵蓋率皆為 100%。
- Spark 耗時 34.296 秒，final 範圍正規化事實涵蓋 100%。
- Luna 耗時 41.096 秒，final 事實涵蓋 0%，訊息合法但過度壓縮。
- 詳細結果見 `docs/model-comparison-2026-07-22.md`。

## 尚未完成的發行閘門

- 真實本機模型的大型多層彙整及排除內容案例。
- 真實 Codex 需要額外 reduce 階段的多層大型案例。
- Spark／Luna 固定 20 案、各 3 次的品質評測。
- oMLX model slug 與版本識別紀錄。

在上述閘門完成前，不安裝至 `~/bin/git-ac`，也不更新全域 Git alias。
