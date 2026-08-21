# git-ac 專案規範

本檔適用於此 repository 內所有檔案。

## 指令與文件同步

- `src/git_ac.py` 是 `git ac` 的實作來源。
- 每次修改 `src/git_ac.py` 都必須檢查 `README.md`；只要參數、環境變數、輸出、前置需求、staging 邊界、安裝／更新方式、錯誤行為或使用流程有任何使用者可觀察的變動，必須在同一個變更中同步更新 `README.md`。
- `README.md` 是唯一的使用者文件，必須持續涵蓋前置設定、安裝與更新、所有指令參數、環境變數、指令行為、限制、安全邊界、錯誤處理及可直接執行的範例。
- 不建立 `docs/` 或獨立的 `git-ac-usage-guide`；需要長期保留的操作或驗收資訊直接整理到 `README.md`。
- `scripts/setup-git-ac.sh` 必須與 `src/git_ac.py` 的檔名、安裝位置及 Git alias 保持一致。變更安裝流程時同步更新腳本、README 與相關測試。

## 測試隔離

- 所有自動測試、手動測試、暫存 Git repository、trace、fixture 輸出與其他測試 artifact，都只能建立在 repository 根目錄的 `.test-workspace/` 下。
- 執行測試時先建立 `.test-workspace/tmp` 與 `.test-workspace/uv-cache`，並設定 `TMPDIR="$PWD/.test-workspace/tmp"`、`UV_CACHE_DIR="$PWD/.test-workspace/uv-cache"`，避免 Python 暫存資料或 `uv` cache 寫到此目錄之外。
- 不得使用此 repository 本身的 index、working tree 或 commit 歷史測試 `git ac`；手動驗證必須在 `.test-workspace/` 下另建 Git repository。
- 一般驗證優先使用 `tests/fakes/bin`，不得連線或消耗模型額度。真實 `aitext`、oMLX 或 Codex 驗收只有在使用者明確要求時才執行，輸出仍須放在 `.test-workspace/`。
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
- 保留 staged snapshot、暫存 index、模型呼叫上限及 commit message 驗證等既有安全邊界；若要放寬，必須有對應測試與 README 說明。
