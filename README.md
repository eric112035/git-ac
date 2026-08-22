# git-ac

`git ac` 會分析 Git 變更，產生繁體中文且符合 Conventional Commits 1.0.0 的 commit message，並建立單一 commit。

## 快速上手

### 1. 安裝 git-ac

在 repository 根目錄執行：

```sh
./scripts/setup-git-ac.sh install
source ~/.zshrc
./scripts/setup-git-ac.sh check
git ac -h
```

### 2. 選擇並準備 backend

請依需求選擇以下其中一條路徑。只有 aichat backend 需要安裝 `aichat` 與 `aitext`；Codex 和 Claude Code 都不經過這兩個工具。

|想使用的服務|Backend|需要準備|
|---|---|---|
|oMLX、本機 model 或自訂 aichat provider|`aichat`|aichat、有效 model/client、`aitext`|
|OpenAI Codex|`codex`|已安裝並登入的 Codex CLI|
|Anthropic Claude Code|`claude`|已安裝並登入的 Claude Code CLI|

#### 路徑 A：aichat（可使用本機或雲端 model）

適合已經有 aichat 設定，或願意自行設定 oMLX 等本機 OpenAI-compatible endpoint／其他 provider 的使用者。

先安裝 aichat：

```sh
brew install aichat
aichat --version
```

第一次執行 `aichat` 時，依提示建立設定；也可以依 [AIChat Configuration Guide](https://github.com/sigoden/aichat/wiki/Configuration-Guide) 自行設定 client、endpoint 與預設 model：

```sh
aichat
aichat --info
aichat --list-models
```

若要使用本機 model，必須先啟動 oMLX 或其他本機服務，並在 aichat 中設定相應 endpoint 與 model。若 aichat 指向雲端 provider，diff 也會送往該 provider；選擇 `aichat` 不代表資料一定留在本機。

aichat 可以正常回應後，再安裝 git-ac 的 `aitext` wrapper：

```sh
./scripts/setup-aitext.sh install
./scripts/setup-aitext.sh check
git ac config set backend aichat
git ac config check
```

git-ac 產生 commit message 時的實際路徑是：

```text
git-ac → aitext → aichat → aichat 設定的 client／endpoint
```

沒有指定 aichat model override 時，`aitext` 不會傳 `-m`，直接沿用 `aichat --info` 顯示的預設 model。

#### 路徑 B：Codex

適合希望直接使用 OpenAI Codex CLI 的使用者，不需要安裝 aichat 或 `aitext`。

依 [OpenAI Docs 的 Codex CLI quickstart](https://developers.openai.com/codex/cli/) 安裝 CLI：

```sh
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
```

進入任一 Git repository 執行 `codex`，依畫面選擇登入方式：

```sh
codex
```

完成登入後，將 Codex 設為 git-ac 預設 backend：

```sh
git ac config set backend codex
git ac config check
git ac config get backend
git ac config get model codex
```

未設定 model 時使用 `gpt-5.6-luna`。如果不想改預設，也可以只在單次執行使用 `git ac -c`。

#### 路徑 C：Claude Code

適合希望直接使用 Anthropic Claude Code 的使用者，不需要安裝 aichat 或 `aitext`。

依 [Claude Code Quickstart](https://code.claude.com/docs/en/quickstart) 安裝 CLI：

```sh
brew install --cask claude-code
claude --version
```

執行 `claude` 並依畫面完成登入；需要時可在互動介面使用 `/login`：

```sh
claude
```

完成登入後，將 Claude Code 設為 git-ac 預設 backend：

```sh
git ac config set backend claude
git ac config check
git ac config get backend
git ac config get model claude
```

未設定 model 時使用 `haiku` alias。如果不想改預設，也可以只在單次執行使用 `git ac --claude`。

### 3. 第一次 preview 與 commit

完成任一 backend 路徑後，進入要提交的 Git repository：

```sh
cd /path/to/your/repository
git ac config show
git ac -e
git ac -p
git ac
```

- `git ac -e`：只估算規模，不呼叫模型。
- `git ac -p`：用目前的預設 backend 產生 preview，不建立 commit。
- `git ac`：產生訊息並建立 commit。
- `git ac -c -p`：改用 Codex 產生 preview。
- `git ac --claude -p`：改用 Claude Code 產生 preview。
- `git ac --backend aichat -p`：改用 aichat 產生 preview。

若目前已有 staged 內容，只會分析及提交該 staged snapshot。若沒有 staged 內容，`-p`／`-e` 只會在隔離 index 模擬 `git add -A`；正式 `git ac` 則會在 backend preflight 成功後執行 `git add -A`。

指定 type 或提供參考資訊：

```sh
git ac -p -t fix
git ac -p -m "修正登入逾時，對應 issue #123"
git ac -p -t feat -m "新增可切換的 backend 設定"
```

### 4. 切換或查看預設 backend

```sh
git ac config show
git ac config get backend

git ac config set backend codex
git ac config set backend claude
git ac config set backend aichat

git ac config unset backend
```

`config unset backend` 會恢復內建預設 `aichat`。如果該電腦沒有安裝及設定 aichat，請明確設定 `codex` 或 `claude`，或每次使用 `-c`／`--claude`。

### 5. 更新已安裝版本

repository 取得新版後執行：

```sh
git pull --ff-only
./scripts/setup-git-ac.sh update
./scripts/setup-git-ac.sh check
```

若新版同時修改了 `aitext` wrapper，且你使用 aichat backend，再執行：

```sh
./scripts/setup-aitext.sh update
./scripts/setup-aitext.sh check
```

## 設計原則

- 預設 backend 是 `aichat`。`git-ac` 經內部 `aitext` wrapper 呼叫使用者既有的 aichat 設定；資料送往本機 oMLX 或遠端服務，取決於 aichat 的 client／endpoint。
- 也可明確選擇官方 Codex CLI 或 Claude Code CLI。backend 失敗時中止，不自動切換。
- 尊重使用者決定的 staged 邊界；沒有 staged 內容時，正式執行才會在所有 backend preflight 成功後執行 `git add -A`。
- 小型 diff 直接產生訊息，大型 diff 自動進行 recursive map-reduce；最終結果仍須通過格式、語言及 staged snapshot 驗證。

## Backend 與預設 model

|Backend|執行路徑|未設定 model 時|
|---|---|---|
|`aichat`|`git-ac` → `aitext` → `aichat`|`aitext` 不傳 `-m`，沿用 aichat 自己的預設 model|
|`codex`|`git-ac` → `codex exec`|`gpt-5.6-luna`|
|`claude`|`git-ac` → `claude --print`|`haiku` alias|

`aitext` 是內部 I/O wrapper，不是 backend。oMLX 是可由 aichat 使用的 client／endpoint，也不是 backend。

[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) 與 Claude Code 的 [`haiku` alias](https://code.claude.com/docs/en/model-config) 是成本敏感的內建 fallback；正式發行前仍須通過專案的 ground-truth commit message 評測。實際 Codex CLI／Claude Code 額度與費用由帳戶方案及官方服務決定，本專案不宣稱固定單次金額。

## 前置條件

- macOS、zsh、Git。
- Python 3.11 以上；執行期不需要第三方 Python 套件。
- Git commit 身分已設定。
- 使用 `aichat` 時需安裝並設定 `aichat`，以及本專案的 `aitext` wrapper。
- 使用 `codex` 時需安裝官方 Codex CLI 並完成登入。
- 使用 `claude` 時需安裝官方 Claude Code CLI 並完成登入。
- 只有開發與測試需要 `uv`。

```sh
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## 安裝與更新

在 repository 根目錄執行：

```sh
./scripts/setup-git-ac.sh install
source ~/.zshrc
./scripts/setup-git-ac.sh check
git ac -h
```

安裝腳本會將 `src/git_ac.py` 安裝為 `$HOME/bin/git-ac`、管理 `.zshrc` 的 PATH 區塊，並設定：

```sh
git config --global alias.ac '!git-ac'
```

安裝或更新 `aitext` wrapper：

```sh
./scripts/setup-aitext.sh install
./scripts/setup-aitext.sh check
```

更新已安裝版本：

```sh
git pull --ff-only
./scripts/setup-git-ac.sh update
./scripts/setup-git-ac.sh check
```

腳本不會靜默覆寫既有且不同的 `alias.ac`。

## CLI

```text
git ac [--backend aichat|codex|claude] [--model MODEL]
       [-c | --claude]
       [-t [TYPE]] [-m MESSAGE]
       [-p] [-e|--estimate]

git ac config show
git ac config check
git ac config get backend
git ac config get model BACKEND
git ac config set backend BACKEND
git ac config set model BACKEND MODEL
git ac config unset backend
git ac config unset model BACKEND
```

|參數|用途|
|---|---|
|`--backend BACKEND`|只覆寫本次執行的 backend|
|`-c`|相容捷徑，等同 `--backend codex`|
|`--claude`|等同 `--backend claude`|
|`--model MODEL`|只覆寫本次 backend 的 model|
|`-t TYPE`、`--type TYPE`|指定 Conventional Commit type|
|`-t`、`--type`|從 `/dev/tty` 顯示 type 選單並選擇|
|`-m MESSAGE`、`--message MESSAGE`|提供 AI 產生訊息時的參考資訊|
|`-p`|只預覽 commit message，不建立 commit|
|`-e`、`--estimate`|估算 diff 規模、分塊與最低模型呼叫數，不呼叫模型|

多個 backend selector 不能同時使用。`-e` 只與 `-p` 互斥，因此可搭配 backend、model、type 與 message：

```sh
git ac -e --backend claude --model sonnet -t feat \
  -m "這次要統一 backend 設定介面"
```

`config` 指令可在 Git repository 外執行。`config get` 只輸出經環境變數、TOML 與內建 fallback 解析後的單一有效值，適合 shell script 使用；`config show` 則同時顯示來源與資料去向。`config check` 不呼叫模型，只檢查選定 backend 的 CLI、model ID 與可離線確認的必要設定；帳戶是否實際獲准使用某個 Codex／Claude model，仍會在正式呼叫時由官方 CLI 判定。

## 設定檔

設定檔位置：

```text
~/Library/Application Support/git-ac/config.toml
```

最小設定：

```toml
version = 1
default_backend = "aichat"
```

Model 覆寫都是選填：

```toml
version = 1
default_backend = "aichat"

[models]
aichat = "omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac"
codex = "gpt-5.6-terra"
claude = "sonnet"
```

設定檔以 `0600` 權限原子寫入；程式會拒絕 symlink、未知 schema version、未知欄位與無效 backend／model。設定中不保存 endpoint、憑證或其他祕密，也不支援 repository-level 設定。

### 解析優先序

Backend：

1. CLI `--backend`、`-c`、`--claude`
2. `GIT_AC_BACKEND`
3. TOML `default_backend`
4. `aichat`

Model：

1. CLI `--model`
2. `GIT_AC_<BACKEND>_MODEL`
3. TOML `[models].<backend>`
4. backend fallback

支援的環境變數：

```text
GIT_AC_BACKEND
GIT_AC_AICHAT_MODEL
GIT_AC_CODEX_MODEL
GIT_AC_CLAUDE_MODEL
GIT_AC_CODEX_MAX_CALLS
GIT_AC_CLAUDE_MAX_CALLS
GIT_AC_MODEL_TIMEOUT
GIT_AC_TRACE_FILE
GIT_AC_TRACE_CASE
```

既有 `DEFAULT_GIT_AC_LOCAL_MODEL` 仍作為 `GIT_AC_AICHAT_MODEL` 的低優先序相容 fallback。

`GIT_AC_MODEL_TIMEOUT` 預設為每次呼叫 120 秒，必須是正整數。`GIT_AC_TRACE_FILE` 可指定權限為 `0600` 的 JSONL 評測 trace；`GIT_AC_TRACE_CASE` 可附加案例名稱。Trace 只包含 backend、model、stage、byte 數、`FACT_` 標記、耗時與成功狀態，不包含 prompt、diff、`--message` 原文或完整模型輸出。

常用設定操作：

```sh
git ac config show
git ac config check
git ac config get backend
git ac config get model aichat
git ac config set backend codex
git ac config set model codex gpt-5.6-terra
git ac config unset model aichat
git ac config unset backend
```

`config show` 會顯示實際解析值及來源。aichat 未覆寫 model 時，也會查詢 aichat 的有效預設：

```text
backend：aichat（built-in）
model：omlx:...（aichat default）
資料去向：由 aichat client／endpoint 設定決定
```

## aichat 設定

git-ac 不修改 aichat YAML。請依 [AIChat Command Line Guide](https://github.com/sigoden/aichat/wiki/Command-Line-Guide) 在 aichat 中自行管理 client、endpoint、憑證、model metadata、`max_tokens`、temperature 與 request patch。

沒有 model override 時：

```text
git-ac → aitext → aichat 預設 model → 使用者設定的 client
```

此時 `aitext` 不傳 `-m`。若目前 aichat 的 top-level `model` 指向 oMLX，git-ac 就會沿用該 oMLX model。

有 model override 時：

```text
git-ac → aitext -m <完整 aichat model ID> → aichat client
```

git-ac 會先用 `aichat --list-models` 驗證完整 ID；沒有 override 時則用 `aichat --info` 確認預設 model 有效。

例如 aichat 設定可包含：

```yaml
model: omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac
```

實際 client 與 model 定義仍以使用者的 aichat 設定為準。執行：

```sh
aichat --info
aichat --list-models
```

確認設定後，再執行：

```sh
git ac config check
git ac -p
```

## Codex backend

未覆寫時使用 `gpt-5.6-luna`。git-ac 會在隔離的暫存 repository 中，以唯讀 sandbox、停用工具及忽略使用者 Codex 設定的方式呼叫 `codex exec`，預設最多 12 次模型呼叫。

執行前會明確提示 staged diff 與 `--message` 參考資訊將傳送至 OpenAI。認證仍由官方 Codex CLI 的全域狀態提供。

```sh
git ac -c -p
git ac --backend codex --model gpt-5.6-terra
```

## Claude backend

未覆寫時使用 `haiku` alias。git-ac 會在隔離的暫存 repository 中使用 `claude --print`，並停用工具、session persistence、一般 settings sources、非空 MCP、slash commands、Chrome、auto memory 與 prompt history，預設最多 12 次模型呼叫。[Claude Code settings](https://code.claude.com/docs/en/settings) 所述的 managed policy 與認證等必要全域狀態仍可能載入。

執行前會明確提示 staged diff 與 `--message` 參考資訊將傳送至 Claude Code。

```sh
git ac --claude -p
git ac --backend claude --model sonnet
```

## Type 選擇

可用 type：

|Type|選擇原則|
|---|---|
|`feat`|新增或擴充功能|
|`fix`|修正錯誤行為|
|`docs`|只有文件變更|
|`style`|只有格式或空白，不代表 UI 樣式功能|
|`refactor`|不改外部行為的結構調整|
|`perf`|改善效能|
|`test`|只有測試變更|
|`build`|建置、依賴或封裝|
|`ci`|CI/CD 設定|
|`chore`|無法歸入其他類型的一般維護|
|`revert`|回復既有變更|

```sh
git ac -t fix
git ac --type feat
git ac --type
```

指定 type 後，若模型回傳不同 type，git-ac 會只替換標題 type，保留 scope、`!`、description、body 與 footer，再執行完整驗證。未指定時，prompt 會依整個 commit 的主要目的判斷；配套測試或文件不主導 type，breaking change 則依 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) 獨立判斷。

## 參考訊息

`--message` 是給 AI 的參考資訊，不是完整 commit message：

```sh
git ac -m "這次是為了解決設定難以攜帶，issue #123"
```

- 必須是非空文字，最多 4,096 UTF-8 bytes，且每次只能提供一次。
- 適合描述目的、術語、issue 編號及設計理由。
- 程式行為、測試結果與相容性聲明仍須由 diff 支持。
- 內容會加入 map、reduce 與 final prompt並納入 budget。
- 不保存於 TOML、trace 或錯誤輸出；重試訊息也不回顯原文。

## Commit message 格式

```text
<type>[optional scope][!]: <繁體中文描述>
```

- `type` 與技術性 `scope` 可保留英文；description 與一般 body 必須包含繁體中文。
- body 為選用，與標題間需有一個空白行。
- breaking change 可用標題的 `!`、`BREAKING CHANGE: <繁體中文說明>` footer，或兩者同時使用。
- 支援 `Refs:`、`Closes:`、`Fixes:` 與 `Relates-to:` 等 footer。
- code fence、模型前言、重複標題、空訊息、未允許 type 或沒有 diff 證據的聲明都會被拒絕。

## Staging、preview 與 estimate

|執行前狀態|正式執行|`-p`／`-e`|
|---|---|---|
|已有 staged 變更|只分析及提交既有 staged snapshot|只分析既有 staged snapshot|
|沒有 staged，working tree 有異動|所有 backend preflight 成功後執行 `git add -A`|用隔離 index 模擬 `git add -A`，真實 index 不變|
|同時有 staged 與 unstaged／untracked|只處理 staged 內容|只處理 staged 內容|

`-p` 會呼叫模型但不建立 commit；`-e` 不呼叫模型，也不要求 backend CLI 已安裝。正式執行與 preview 都會在模型呼叫後再次確認 snapshot 未變。

```sh
git ac -e
git ac -p
git ac --claude -p
git ac -c
```

## 大型 diff 與呼叫上限

大型 diff 會依檔案、hunk 與行切塊，先 map，再 recursive reduce，最後生成 commit message。任何 backend 都不會因總 bytes 超過固定值而直接拒絕，但會受到 prompt budget 及呼叫上限保護。

Codex 與 Claude 預設各最多 12 次呼叫，可用對應環境變數調整。若估算已超過上限，指令會在呼叫模型前失敗；執行中達到上限也會立即停止，不會切換 backend。

## 安全邊界

- 不解析、追蹤或恢復 ignored 檔案內容。
- binary diff 只保留 metadata，不將 binary payload 傳給模型。
- Lockfile 與刪除檔案只提供狀態及路徑，避免展開大量產生內容或已刪除內容。
- Cloud backend 會先顯示資料去向；aichat 的資料去向由其 client／endpoint 決定。
- Backend preflight 在可能的 `git add -A` 之前完成。
- Backend 失敗不自動 fallback，並保留 staged snapshot。
- 設定檔不保存祕密，`--message` 不寫入 trace。
- AI 只產生文字，不能操作 repository 或呼叫工具。

## 開發與測試

```sh
mkdir -p .test-workspace/tmp .test-workspace/uv-cache
TMPDIR="$PWD/.test-workspace/tmp" \
UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
uv run python -m unittest discover -s tests -v
```

離線測試使用 fake `aitext`、`aichat`、`codex` 與 `claude`，不會呼叫真實模型。

取得明確授權後，可分別執行小型真實 preview smoke test：

```sh
GIT_AC_RUN_AICHAT_INTEGRATION=1 \
TMPDIR="$PWD/.test-workspace/tmp" \
UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
uv run python -m unittest \
  tests.test_real_integration.RealAichatBackendTests.test_real_aitext_small_preview -v

GIT_AC_RUN_CODEX_INTEGRATION=1 \
TMPDIR="$PWD/.test-workspace/tmp" \
UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
uv run python -m unittest \
  tests.test_real_integration.RealCodexBackendTests.test_real_codex_small_preview -v
```

兩者都使用隔離的 `.test-workspace/` repository 與 `-p`，驗證真實模型輸出、Conventional Commit 格式、staged snapshot 不變及沒有建立 commit。Codex 測試明確指定 `gpt-5.6-luna`。

真實模型整合測試是 opt-in；只有在明確允許外部呼叫與額度消耗時執行。Luna 與 Haiku 必須在固定 ground-truth 案例中通過小型、混合型、大型 map/reduce、breaking change、必要事實及 hallucination 門檻，才可視為可發行預設。

明確同意使用 Codex／Claude 額度後，可執行共同 release gate：

```sh
TMPDIR="$PWD/.test-workspace/tmp" \
UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
uv run python tests/run_real_backend_eval.py \
  --output .test-workspace/backend-eval.json
```

可用 `--backend codex` 或 `--backend claude` 只評測單一 backend，並以 `--codex-model`、`--claude-model` 覆寫候選 model。程式只在所有案例的 type、格式、事實保留、breaking change、虛構內容與 snapshot 檢查都通過時回傳成功。
