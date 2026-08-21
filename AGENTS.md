# git-ac 專案規範

本檔適用於此 repository 內所有檔案。

## 長期目標與架構邊界

- `git ac` 的長期目標是把使用者已決定的 staged snapshot 產生為一則繁體中文 Conventional Commits 訊息，並且只建立一個 commit；不得由 AI 自動改變 staging 邊界或拆分 commit。
- 本機優先是產品預設：`git ac` 固定走 `aitext` → `aichat` → oMLX，資料留在本機；只有使用者明確指定 `-c` 時才可把完整分析內容送往官方 `codex exec`。任一後端失敗時不得自動切換後端。
- 大型 diff 應透過檔案／hunk／行切塊與 recursive map-reduce 處理，不得重新加入總 diff bytes 的固定拒絕上限；所有路徑仍須維持單一 commit 與 staged snapshot 一致性。
- `src/aitext` 是本專案自製 wrapper 的唯一來源，只負責避免 REPL、轉交 `aichat` 參數與 stdin、去除 `<think>` 區段、保留 `aichat` exit code 及正規化結尾換行；模型 client、endpoint 與 profile 由使用者在 `aichat`／oMLX 設定中管理。
- Codex 後端直接使用官方 CLI，不經 `aichat`、`aitext` 或 `CLIProxyAPI`。後端、預設模型、prompt budget 或模型呼叫上限是版本化的整體決策，變更時必須同步更新評測、測試與 README，不能依單一 diff 靜默切換。

## 指令與文件同步

- `src/git_ac.py` 是 `git ac` 的實作來源。
- 每次修改 `src/git_ac.py` 都必須檢查 `README.md`；只要參數、環境變數、輸出、前置需求、staging 邊界、安裝／更新方式、錯誤行為或使用流程有任何使用者可觀察的變動，必須在同一個變更中同步更新 `README.md`。
- `README.md` 是唯一的使用者文件，必須持續涵蓋前置設定、安裝與更新、所有指令參數、環境變數、指令行為、限制、安全邊界、錯誤處理及可直接執行的範例。
- 不建立 `docs/` 或獨立的 `git-ac-usage-guide`；需要長期保留的操作或驗收資訊直接整理到 `README.md`。
- `scripts/setup-git-ac.sh` 必須與 `src/git_ac.py` 的檔名、安裝位置及 Git alias 保持一致。變更安裝流程時同步更新腳本、README 與相關測試。
- `scripts/setup-aitext.sh` 必須與 `src/aitext` 的行為、安裝位置及 `aichat` 前置需求保持一致；變更 wrapper 或本機後端設定時同步更新腳本、README 與相關測試。

## 測試隔離

- 所有自動測試、手動測試、暫存 Git repository、trace、fixture 輸出與其他測試 artifact，都只能建立在 repository 根目錄的 `.test-workspace/` 下。
- 執行測試時先建立 `.test-workspace/tmp` 與 `.test-workspace/uv-cache`，並設定 `TMPDIR="$PWD/.test-workspace/tmp"`、`UV_CACHE_DIR="$PWD/.test-workspace/uv-cache"`，避免 Python 暫存資料或 `uv` cache 寫到此目錄之外。
- 不得使用此 repository 本身的 index、working tree 或 commit 歷史測試 `git ac`；手動驗證必須在 `.test-workspace/` 下另建 Git repository。
- 一般驗證優先使用 `tests/fakes/bin`，不得連線或消耗模型額度。真實 `aitext`、oMLX 或 Codex 驗收只有在使用者明確要求時才執行，輸出仍須放在 `.test-workspace/`。
- fake 後端測試只能證明 orchestration 與安全邊界；發行本機後端前仍需完成真實 `aitext`／aichat／oMLX 驗收，發行或變更 Codex 預設模型前仍需用固定 ground truth 評測集驗證格式、必要事實、breaking change 與虛構內容門檻。
- 修改指令後至少執行受影響測試；若改到共用流程，執行完整離線測試：

  ```sh
  mkdir -p .test-workspace/tmp .test-workspace/uv-cache
  TMPDIR="$PWD/.test-workspace/tmp" \
    UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
    uv run python -m unittest discover -s tests -v
  ```

## 修改原則

- 僅支援並記錄 macOS 與 zsh 使用情境。
- 安裝腳本必須可重複執行，不得靜默覆寫既有且不同的 Git alias 或非本專案管理的 shell 設定。
- `setup-aitext.sh install` 不得靜默覆寫內容不同的既有 `~/bin/aitext`；只有使用者明確執行 `update` 時才可更新既有一般檔案。
- 保留 staged snapshot、暫存 index、模型呼叫上限及 commit message 驗證等既有安全邊界；若要放寬，必須有對應測試與 README 說明。
