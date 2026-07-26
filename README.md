# git-ac

`git ac` 的開發版本。它只分析目前的 staged snapshot，使用本機 `aitext`（預設）或官方 `codex exec`（`-c`）產生繁體中文 Conventional Commits 訊息，最後建立一個 commit。本機模式預設指定 oMLX 的 `mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac` profile，將 commit message 工作與其他本機模型用途隔離。

目前先從原始碼執行：

```sh
uv run python src/git_ac.py -e
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
- index 為空但 working tree 有變更時，一般模式會實際執行 `git add -A`。
- index 為空時，`-p` 與 `-e` 使用隔離的暫存 index／object database 模擬 `git add -A`；會分析 tracked、unstaged 與 untracked 變更，但真實 index 與專案 object database 不會改變。

模型執行前會在 stderr 列出「納入 AI 完整 diff 分析」與「排除完整內容、只提供狀態與路徑」的檔案。特殊檔名會安全跳脫；每組最多列出 100 筆，其餘顯示省略數量。commit message 或 `-p` 的 stdout 不會被這些資訊污染。

## 執行前估算

直接估算所有尚未提交的變更：

```sh
git ac -e
```

若只想估算特定 commit 範圍，先手動 `git add <檔案>`；只要 index 已有 staged 內容，估算就不會納入其餘 unstaged／untracked 檔案。

`-e` 是 `--estimate` 的短參數。它依正式執行使用的同一套排除與分塊邏輯，列出完整分析／排除檔案數、增刪行數、有效分析量、map chunks、最低模型呼叫數、Codex 上限及本機／Codex 建議。它不呼叫模型、不建立 commit、不改變真實 index，也不需要 `aitext` 或 `codex` 可用；不可與 `-c` 或 `-p` 同時使用。

規模建議採 OR 判定：完整分析檔案不超過 5 個、異動不超過 300 行且不需分塊時為小型；超過其中任一條件為中型；超過 20 個檔案、1,000 行或至少 4 個 map chunks 時為大型。若 Codex 最低呼叫數已超過目前上限，則標示為超大型。敏感內容不論規模都應使用本機 `git ac`。

完整操作說明見 [`docs/git-ac-usage-guide.md`](docs/git-ac-usage-guide.md)。

## 本機模型與輸出上限

本機模式固定透過以下命令呼叫 `aitext`，不會改變平常直接使用 `aitext` 時的預設模型：

```sh
aitext -m omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac
```

單次需要改用其他本機模型時：

```sh
DEFAULT_GIT_AC_LOCAL_MODEL=omlx:custom-model git ac
```

空白的 `DEFAULT_GIT_AC_LOCAL_MODEL` 會直接報錯，不會退回 `aichat` 的全域預設模型。

建議在 `aichat` 的 `omlx` client 登錄 git 專用 profile，並只對這個 model ID 注入 `max_tokens: 1024` 與 `temperature: 0`：

```yaml
clients:
  - type: openai-compatible
    name: omlx
    api_base: http://localhost:8000/v1
    models:
      - name: mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac
        max_input_tokens: 131072
        max_output_tokens: 1024
    patch:
      chat_completions:
        '^mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac$':
          body:
            max_tokens: 1024
            temperature: 0
```

在 `aichat 0.30.0` 中，`max_output_tokens` 是模型能力／context metadata，不會自行加入 OpenAI-compatible request；真正送到 oMLX 的是 `patch.chat_completions.<model>.body.max_tokens`。oMLX log 應顯示：

```text
max_tokens=1024, request_max_tokens=1024
```

48,000-byte prompt budget 限制輸入 diff；`max_tokens: 1024` 限制模型輸出，兩者互不取代。oMLX 的 `git-ac` profile 應設定 context window 131,072、Max Tokens 1,024、temperature 0，並實際關閉「啟用思考」；profile 名稱本身不會套用這些參數。

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
