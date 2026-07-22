# git-ac

`git ac` 的開發版本。它只分析目前的 staged snapshot，使用本機 `aitext`（預設）或官方 `codex exec`（`-c`）產生繁體中文 Conventional Commits 訊息，最後建立一個 commit。

目前先從原始碼執行：

```sh
uv run python src/git_ac.py -p
uv run python src/git_ac.py
uv run python src/git_ac.py -c -p
```

執行測試：

```sh
uv run python -m unittest discover -s tests -v
```

一般測試只使用 `tests/fakes/bin` 的假後端，不會連線或消耗模型額度。真實本機大型 diff、真實 Spark／Luna 及實際 commit 路徑均已有驗收紀錄；完整 20 案、每個模型各 3 次的統計品質評測仍待完成。

## Staging 邊界

- index 已有 staged 變更時，只分析及提交既有 staged snapshot，不會再執行 `git add -A`。
- index 為空但 working tree 有變更時，一般模式才會自動執行 `git add -A`。
- `-p` 永遠不自動 staging。

模型執行前會在 stderr 列出「納入 AI 完整 diff 分析」與「排除完整內容、只提供狀態與路徑」的檔案。特殊檔名會安全跳脫；每組最多列出 100 筆，其餘顯示省略數量。commit message 或 `-p` 的 stdout 不會被這些資訊污染。

## Codex 呼叫上限

`git ac -c` 預設最多呼叫 Codex 12 次，避免超大型 diff 在未確認下消耗過多額度。大型 diff 在第一個 request 前會先計算 map chunks 與 final 的最低呼叫數；若已超過上限便直接中止，staged snapshot 保持不變。

12 次在摘要可直接進入 final 的一般情況下，約可容納 11 個 map chunks，也就是約 500 KB 的文字 diff。實際大小會因檔案邊界、UTF-8 bytes 與摘要長度而異。執行中若 recursive reduce 使總呼叫數達到上限，也會停止並保留 staged 內容。

本機 `git ac` 不設呼叫次數上限，只受單次模型 timeout 限制。確定要讓 Codex 處理更大的 staged diff 時，可明確提高上限：

```sh
GIT_AC_CODEX_MAX_CALLS=20 git ac -c
```

每次執行都會在 stderr 顯示預估的最低呼叫數、chunk 進度及實際模型呼叫次數。

真實本機小型預覽驗收需明確啟用：

```sh
GIT_AC_RUN_LOCAL_INTEGRATION=1 uv run python -m unittest tests.test_real_integration -v
```

以相同的大型合成 staged diff 比較真實 Spark 與 Luna，並只保存 stage metrics：

```sh
uv run python tests/run_real_codex_compare.py --target-kb 180
```

以約 150 KB 合成 staged diff 執行真實本機 `aitext`／oMLX 大型 chunk 驗收：

```sh
uv run python tests/run_real_local_large.py --target-kb 150
```

可設定 `GIT_AC_TRACE_FILE` 寫入權限為 `0600` 的 JSONL 驗收紀錄。紀錄只包含 backend、model、stage、prompt/output byte 數、`FACT_` 驗收標記、耗時與成功狀態，不包含 prompt、diff 或完整模型輸出。
