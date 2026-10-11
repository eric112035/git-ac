# git-ac 專案規範

本檔適用於此 repository 內所有檔案。

## 長期目標與架構邊界

- `git ac` 的長期目標是把使用者已決定的 staged snapshot 產生為一則繁體中文 Conventional Commits 訊息，並且只建立一個 commit；不得由 AI 自動改變 staging 邊界或拆分 commit。
- 預設 backend 由固定品質評測決定：AFM 的六個 ground-truth 案例連續三次全部通過之前，保留 aichat 預設；AFM 可明確選用。既有使用者明確設定不得被升級覆寫。任一 backend 失敗時不得自動切換。
- AFM 直接呼叫 macOS 27 官方 `fm` CLI，只支援本機 `system` model。自動 staging 前檢查授權與模型可用性；只引導使用者自行執行 `sudo fm license`，不得代為同意授權。
- AFM 每個完整 prompt 以 `fm count-tokens --quiet` 檢查 3,000-token 輸入預算；aichat 預設 24,000 bytes（環境變數可調整為 8,000–48,000）；Codex／Claude 維持 48,000 bytes。Map／reduce 摘要以 1,000 UTF-8 bytes 為長度目標，不可直接截斷丟棄證據。
- aichat／AFM 的 map／reduce 逾時只將該批拆小重試一次，子批次不得遞迴重試；final／repair 逾時直接中止。模型程序須以獨立 process group 啟動並在逾時或取消時清理整組子程序。
- 預設快速模式：完整文字能同時容納 final／repair 時全部納入，超量才使用有來源座標的穩定代表片段；明示省略量，不保證完整 breaking change 涵蓋。最多 final＋一次 repair，不跑 map-reduce。
- `-f／--full` 使用整理後的完整可分析文字執行 recursive map-reduce，不截斷證據。所有 backend 預設 12 次生成上限，`-n／--max-calls` 僅適用完整模式；超過已知最低呼叫預算須在生成前中止，不得重新加入總 diff bytes 的固定拒絕上限。
- `-T／--max-time` 限制整段分析（含 preflight、整理及 token 計數），快速／完整預設 120／300 秒。每次外部程序受單次 timeout 與剩餘期限共同限制；期限到期清理程序且不重試。Git commit／hook 不計入 AI 期限。
- 僅減量可驗證解碼的大型單行媒體 Base64 data URI，保留新增／刪除／未變更狀態、MIME、大小與 SHA-256；建置產物只依分析版本的 `linguist-generated=set/true` 標記，不依 dist／build 路徑推測。維持 unified=3。
- `src/aitext` 是本專案自製 wrapper 的唯一來源，只負責避免 REPL、轉交 `aichat` 參數與 stdin、去除 `<think>` 區段、保留 `aichat` exit code 及正規化結尾換行；它是內部 wrapper，不是公開 backend。模型 client、endpoint 與 profile 由使用者在 aichat 設定中管理，git-ac 不修改 aichat YAML。
- Codex 與 Claude backend 直接使用各自官方 CLI，不經 `aichat`、`aitext` 或 `CLIProxyAPI`。backend、可選 model、設定 schema、預設模型、prompt budget 或模型呼叫上限是版本化的整體決策，變更時必須同步更新評測、測試與 README，不能依單一 diff 靜默切換。

## 指令與文件同步

- `src/git_ac.py` 是 `git ac` 的實作來源。
- `README.md` 是專案入口文件，必須持續涵蓋專案定位、前置需求、快速安裝與更新、最短可執行範例、重要安全邊界及完整 Wiki 連結。
- `../git-ac-wiki` 是附屬 GitHub Wiki 的本機 repository，作為完整使用者與開發者文件；必須涵蓋所有指令參數、環境變數、安裝與更新、指令行為、限制、安全邊界、錯誤處理、疑難排解、架構及可直接執行的範例。
- 每次修改 `src/git_ac.py` 都必須檢查 `README.md` 與 `../git-ac-wiki` 的相關頁面；只要參數、環境變數、輸出、前置需求、staging 邊界、安裝／更新方式、錯誤行為或使用流程有任何使用者可觀察的變動，必須在同一個工作內同步更新兩邊的相關內容。
- 架構、backend 整合、開發流程或維護方式有實質變更時，即使不影響一般使用者操作，也必須檢查並更新 Wiki 的相關架構或開發文件。
- 純內部重構、格式調整，或只調整測試且不改變既有行為時，不要求修改使用者文件。
- 不在此 repository 建立 `docs/` 或獨立的 `git-ac-usage-guide`；不適合放在入口 README 的長篇操作、驗收、架構或疑難排解資訊整理到 `../git-ac-wiki`。
- `scripts/setup-git-ac.sh` 必須與 `src/git_ac.py` 的檔名、安裝位置及 Git alias 保持一致。變更安裝流程時同步更新腳本、README、Wiki 相關頁面與相關測試。
- `scripts/setup-aitext.sh` 必須與 `src/aitext` 的行為、安裝位置及 `aichat` 前置需求保持一致；變更 wrapper 或本機後端設定時同步更新腳本、README、Wiki 相關頁面與相關測試。
- 若 `../git-ac-wiki` 不存在或不在可寫入的 workspace 範圍內，必須在交付摘要列出尚未同步的文件、原因及預期頁面，不得宣稱文件同步完成。
- `git-ac` 與 `git-ac-wiki` 是不同的 Git repository，文件同步是同一工作內的跨 repository 變更，不可能落在同一個 commit；未經使用者明確要求，不得自行 commit 或 push 任一 repository。

## 測試隔離

- 所有自動測試、手動測試、暫存 Git repository、trace、fixture 輸出與其他測試 artifact，都只能建立在 repository 根目錄的 `.test-workspace/` 下。
- 執行測試時先建立 `.test-workspace/tmp` 與 `.test-workspace/uv-cache`，並設定 `TMPDIR="$PWD/.test-workspace/tmp"`、`UV_CACHE_DIR="$PWD/.test-workspace/uv-cache"`，避免 Python 暫存資料或 `uv` cache 寫到此目錄之外。
- 不得使用此 repository 本身的 index、working tree 或 commit 歷史測試 `git ac`；手動驗證必須在 `.test-workspace/` 下另建 Git repository。
- 一般驗證優先使用 `tests/fakes/bin` 的 fake `aitext`、`aichat`、`codex` 與 `claude`，不得連線或消耗模型額度。真實 aichat client、Codex 或 Claude 驗收只有在使用者明確要求時才執行，輸出仍須放在 `.test-workspace/`。
- fake backend 測試只能證明 orchestration 與安全邊界；發行 aichat backend 前仍需完成真實 `aitext`／aichat 驗收。發行或變更 Codex、Claude 預設 model 前，必須用固定 ground truth 評測集驗證繁體中文、Conventional Commits、map/reduce 必要事實、breaking change 與虛構內容門檻。
- 快速／完整模式驗收明確選擇 backend，使用 `tests/run_real_backend_eval.py --backend BACKEND --suite modes --repeats 3`：六個固定案例快速模式各三次、大型案例完整模式三次、合成旅遊網站快速模式三次。快速模式不要求 map，但必要事實、breaking change 與虛構內容門檻不得降低；報告按模式記錄預算、納入／省略量、呼叫及耗時。
- 修改指令後至少執行受影響測試；若改到共用流程，執行完整離線測試：

  ```sh
  mkdir -p .test-workspace/tmp .test-workspace/uv-cache
  TMPDIR="$PWD/.test-workspace/tmp" \
    UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
    uv run python -m unittest discover -s tests -v
  ```

### 測試 artifact 生命週期

- 測試自動建立的 case repository、temporary index、trace、fake backend log、測試用 home 與 fixture 輸出都是可重建的暫存物。測試正常結束或 assertion 失敗時，必須透過 `TemporaryDirectory`、`tearDown` 或 `finally` 自動清除。
- `GIT_AC_KEEP_TEST_REPOS=1` 只能用於明確的除錯需求。診斷完成後，必須在同一個工作內清除因此保留的 case 目錄；只有使用者明確要求保留時才能留下，並須在交付摘要列出路徑與用途。
- `.test-workspace/tmp/` 目錄可保留供後續測試使用，但其中的暫存檔、lock、被中斷測試留下的目錄與其他一次性內容應在測試完成後清除。
- `.test-workspace/uv-cache/` 是可跨次重用的 dependency cache，預設保留；只有 cache 損壞、版本問題、空間清理或使用者明確要求時才清除。
- 透過評測指令的 `--output` 明確命名的 JSON 報告，以及人工選定的 ground-truth／benchmark baseline，可以跨次保留作為模型比較與發行依據。這些檔案不得包含 diff 原文、prompt、`--message` 內容、憑證或其他敏感資訊；若只是臨時 debug 輸出則不屬於可保留報告。
- `setup-debug-home`、`real-*`、個別測試名稱目錄、未明確指定輸出位置的 JSON／JSONL、trace 與 backend log，均視為一次性除錯殘留，不得在工作完成後留下。若測試被中斷而無法執行 teardown，下一次開始測試或本次交付前必須補做清理。
- 不得為了清除暫存物而整體刪除 `.test-workspace/`，以免同時移除可重用的 `uv-cache` 或刻意保留的評測報告。清除前先解析並確認精確目標，只移除確定屬於本次測試的路徑。
- 執行過測試後，交付前必須盤點 `.test-workspace/`；確認一次性 artifact 已清除，並在摘要說明刻意保留的 cache、評測報告或除錯資料。若沒有任何刻意保留項目，目錄中除 `tmp/` 與 `uv-cache/` 外不應有其他內容。

## 修改原則

- 僅支援並記錄 macOS 與 zsh 使用情境。
- 安裝腳本必須可重複執行，不得靜默覆寫既有且不同的 Git alias 或非本專案管理的 shell 設定。
- `setup-aitext.sh install` 不得靜默覆寫內容不同的既有 `~/bin/aitext`；只有使用者明確執行 `update` 時才可更新既有一般檔案。
- 保留 staged snapshot、暫存 index、模型呼叫上限及 commit message 驗證等既有安全邊界；若要放寬，必須有對應測試與 README 說明。
