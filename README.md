# git-ac

`git ac` 會分析 Git 變更，產生一則繁體中文、符合 Conventional Commits 1.0.0 的 commit message，並建立單一 commit。

## 專案目標

- 預設使用本機模型，diff 不離開電腦；只有明確執行 `git ac -c` 才使用 Codex。
- 尊重使用者決定的 staged 邊界，無論變更大小都只建立一個 commit，不由 AI 自動 staging 或拆分 commit。
- 小型 diff 直接產生訊息，大型 diff 自動依檔案、hunk 與行切塊，再以 recursive map-reduce 彙整；不以總 diff bytes 作為拒絕提交的固定上限。
- 最終訊息必須通過 Conventional Commits、繁體中文與安全格式驗證；任一後端失敗時中止並保留 staged 內容，不自動切換本機或雲端後端。

## 執行架構

它提供兩個模型後端：

- `git ac`：`git-ac` → 自製 `aitext` wrapper → `aichat` → oMLX → 本機模型。預設指定 `mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac` profile。
- `git ac -c`：`git-ac` → 官方 `codex exec` → OpenAI。預設模型為 `gpt-5.3-codex-spark`。

兩個後端共用相同的 staged 邊界、排除規則、大型 diff 分塊、訊息格式驗證與 snapshot 安全檢查，主要差異是隱私、速度及 Codex 額度成本。

本機路徑中的 [`aichat`](https://github.com/sigoden/aichat) 是連接 OpenAI-compatible endpoint 的通用 CLI；本專案的 `aitext` 則是很薄的輸入／輸出包裝層，不負責載入模型或保存 endpoint 設定。Codex 路徑直接使用官方 CLI，不經 `aichat`、`aitext` 或 `CLIProxyAPI`，以減少額外代理、OAuth 相容性與請求格式風險。

## 前置設定

本專案只考慮 macOS 與 zsh。安裝前請確認：

```sh
git --version
python3 --version
zsh --version
```

必要條件：

- macOS、zsh 與 Git。
- Python 3.11 以上。安裝後的 `~/bin/git-ac` 會透過 `/usr/bin/env python3` 執行，不需要額外 Python 套件。
- Git commit 身分已設定：

  ```sh
  git config --global user.name "Your Name"
  git config --global user.email "you@example.com"
  ```

- 使用本機模式時，需先完成下方的 oMLX 與 `aichat` 設定，再用 `scripts/setup-aitext.sh` 安裝本專案的 `aitext` wrapper。
- 使用 `-c` 時，需安裝官方 `codex` CLI 並完成登入。
- 只有開發及執行測試時需要 `uv`；安裝後的日常指令不依賴 `uv`。

`git ac -e` 不呼叫模型，因此即使尚未安裝 `aitext` 或 `codex` 也能使用。

## macOS 快速安裝

先進入 clone 下來的專案根目錄，再執行：

```sh
./scripts/setup-git-ac.sh install
exec zsh
./scripts/setup-git-ac.sh check
git ac -h
```

以上流程會安裝 `git-ac` 本身。若要使用預設的本機模式，還要完成「[本機 aichat／aitext／oMLX 設定](#本機-aichataitextomlx-設定)」；只使用 `git ac -c` 時可略過本機後端。

省略參數時預設也是 `install`：

```sh
./scripts/setup-git-ac.sh
```

安裝腳本會：

1. 將 `src/git_ac.py` 複製成 `$HOME/bin/git-ac` 並設定為 `755`。
2. 在 `~/.zshrc` 加入有明確起訖標記的 `$HOME/bin` PATH 設定。
3. 以 `git config --global alias.ac '!git-ac'` 設定使用者層級 Git alias。
4. 保留其他 `.zshrc` 與 `.gitconfig` 內容。

在使用者 `eric` 的 Mac 上，實際安裝位置就是：

```text
/Users/eric/bin/git-ac
```

其他使用者會自動安裝到 `/Users/<使用者名稱>/bin/git-ac`，不需要修改腳本。

若全域 `alias.ac` 已存在而且不是 `!git-ac`，腳本會在修改任何設定前中止，不會靜默覆寫。先自行確認並更名或移除既有 alias，再重新執行：

```sh
git config --global --get alias.ac
git config --global --unset alias.ac
./scripts/setup-git-ac.sh install
```

`--unset` 會刪除既有 alias，只有確定不再需要原設定時才執行。

### 設定腳本參數

|參數|行為|
|---|---|
|`install`|安裝或重新安裝執行檔，補上 `.zshrc` PATH 區塊，並設定全域 `alias.ac`；預設動作|
|`update`|只以目前 repository 的 `src/git_ac.py` 更新既有 `$HOME/bin/git-ac`|
|`check`|檢查執行檔、`.zshrc` 管理區塊、全域 alias 與 `git-ac -h`|
|`help`、`-h`、`--help`|顯示設定腳本說明|

### 更新已安裝的 git-ac

repository 取得新版 `git_ac.py` 後，執行：

```sh
git pull --ff-only
./scripts/setup-git-ac.sh update
./scripts/setup-git-ac.sh check
```

`update` 不會重寫 `.zshrc` 或 `.gitconfig`，只會快速更新 `$HOME/bin/git-ac`。如果尚未安裝，會要求先執行 `install`。

若不想使用腳本，也可以手動完成相同設定：

```sh
mkdir -p "$HOME/bin"
install -m 755 src/git_ac.py "$HOME/bin/git-ac"
printf '\nexport PATH="$HOME/bin:$PATH"\n' >> "$HOME/.zshrc"
git config --global alias.ac '!git-ac'
exec zsh
```

手動做法不會偵測重複 PATH 或 alias 衝突，建議優先使用設定腳本。

## git ac 指令參數

```text
git ac [-h] [-c] [-p] [-e]
```

|參數|完整名稱|指令說明|
|---|---|---|
|`-h`|`--help`|顯示 help 後結束|
|`-c`|—|改用官方 Codex CLI；未指定時使用本機 `aitext`／oMLX|
|`-p`|—|只預覽模型產生的 commit message，不建立 commit，也不改變真實 index|
|`-e`|`--estimate`|估算分析規模、分塊與最低模型呼叫數；不呼叫模型、不建立 commit，也不改變真實 index|

`-e` 不可與 `-c` 或 `-p` 同時使用：

```sh
git ac -e -c  # 無效
git ac -e -p  # 無效
```

常用組合：

|指令|呼叫模型|建立 commit|無 staged 時的行為|
|---|---|---|---|
|`git ac -e`|否|否|以隔離的暫存 index 模擬全部變更|
|`git ac -p`|本機|否|以隔離的暫存 index 模擬全部變更|
|`git ac -c -p`|Codex|否|以隔離的暫存 index 模擬全部變更|
|`git ac`|本機|是|實際執行 `git add -A` 後建立 commit|
|`git ac -c`|Codex|是|實際執行 `git add -A` 後建立 commit|

先執行 `-p` 再正式執行會呼叫模型兩次，而且兩次訊息可能不同。只想判斷規模時應使用 `git ac -e`。

## Commit message 格式

標題固定為：

```text
<type>[optional scope][!]: <繁體中文描述>
```

允許的 `type` 為：

```text
build chore ci docs feat fix perf refactor revert style test
```

- `type` 與技術性 `scope` 可保留英文；description 與一般 body 必須包含繁體中文。
- body 為選用，存在時必須和標題間保留一個空白行。
- breaking change 可用標題中的 `!`、`BREAKING CHANGE: <繁體中文說明>` footer，或兩者同時使用。
- 支援 `Refs:`、`Closes:`、`Fixes:` 與 `Relates-to:` 等 footer。
- code fence、模型前言、重複標題、空訊息與未允許的 type 都會被拒絕；驗證失敗時不建立 commit。

## 建議的日常流程

想估算目前所有尚未提交的變更，直接執行：

```sh
git ac -e
```

不需要先執行 `git add`。如果只想分析特定 commit 範圍，才先 staging：

```sh
git add <這次要提交的檔案>
git ac -e
```

再依估算結果選擇：

```sh
git ac       # 本機模型並建立 commit
git ac -c    # Codex Spark 並建立 commit
```

只想先看 commit message：

```sh
git ac -p       # 本機預覽
git ac -c -p    # Codex 預覽
```

選擇原則：

```text
git ac -e
    ↓
小型或敏感內容 → git ac
中大型且非敏感 → git ac -c
超大型 → 優先拆分 commit
```

## Staging 邊界

`git ac` 永遠優先尊重目前已 staged 的內容。

|執行前狀態|指令|行為|
|---|---|---|
|已有 staged 變更|`git ac`|只分析及提交既有 staged snapshot|
|已有 staged，另有 unstaged／untracked|`git ac`|不會加入 unstaged／untracked|
|沒有 staged，但 working tree 有異動|`git ac`|實際執行 `git add -A` 後 commit|
|已有 staged|`git ac -p`|只預覽既有 staged snapshot|
|沒有 staged|`git ac -p`|暫存模擬 `git add -A` 後預覽，真實 index 不變|
|已有 staged|`git ac -e`|只估算既有 staged snapshot|
|沒有 staged|`git ac -e`|暫存模擬 `git add -A` 後估算，真實 index 不變|

### 分析全部變更

不需要先 staging：

```sh
git ac -e
git ac -p
```

兩者都會用隔離的暫存 index 模擬所有變更。後續正式執行 `git ac` 才會真的執行 `git add -A` 並建立 commit。

### 只分析部分檔案

先手動 staging：

```sh
git add src/login.py tests/test_login.py
git ac -e
git ac
```

即使工作目錄還有其他 unstaged 或 untracked 檔案，也不會混入這次估算及 commit。

## Estimate 估算模式

```sh
git ac -e
git ac --estimate
```

估算模式使用正式執行的同一套檔案納入／排除規則、diff 組裝、prompt 大小限制、map chunk 規劃與 Codex 呼叫上限，但不會：

- 呼叫本機模型或 Codex。
- 建立 commit。
- 對真實 index 執行 `git add -A`。
- 改變真實 staged snapshot。
- 在專案 `.git/objects` 留下暫存物件。
- 要求 `aitext` 或 `codex` 已安裝。

如果目前沒有 staged 內容，例如：

```text
 M src/app.py
?? tests/test_app.py
```

工具會建立隔離的暫存 index 與 Git object database，在其中模擬 `git add -A`，分析 tracked、unstaged 與 untracked 變更，完成後刪除暫存環境。終端會顯示：

```text
目前沒有 staged 變更；以下以暫存 index 模擬 git add -A，真實 index 不會改變。
```

執行後原本的 `git status --short` 不會改變。

### 估算輸出

```text
納入 AI 完整 diff 分析的檔案（18）：
  M "src/app.py"
  A "src/config.py"
  ...

排除完整內容、只提供狀態與路徑的檔案（3）：
  M "package-lock.json"（lockfile）
  D "src/legacy.py"（刪除檔案）

git ac 估算結果：
  分析檔案：21（完整分析 18，排除完整內容 3）
  完整分析文字異動：+1240 / -318 行（合計 1558 行）
  有效分析內容：174.2 KiB
  處理方式：4 個 map chunks + 1 次 final
  預估模型呼叫：至少 5 次
  Codex 上限：在目前 12 次上限內
  規模判定：大型
  建議：內容不敏感且重視速度時，建議使用 git ac -c；敏感內容仍使用本機 git ac。
```

日常判斷以完整分析檔案數、排除檔案數、增刪行數、map chunk 數、最低模型呼叫數、規模判定及建議為主。KiB 用來輔助辨識大型 JSON、SQL、長字串、單行產生檔等「行數少但 bytes 很大」的內容。

### 規模判定

`git ac -e` 採 OR 判定，只要符合其中一項就提高規模等級。

|規模|判定條件|一般建議|
|---|---|---|
|小型|完整分析檔案不超過 5 個、合計不超過 300 行、可直接 final|`git ac`|
|中型|超過 5 個檔案、超過 300 行，或需要 1～3 個 map chunks|本機可處理；非敏感且重視速度可用 `git ac -c`|
|大型|超過 20 個檔案、超過 1,000 行，或至少 4 個 map chunks|非敏感內容建議 `git ac -c`|
|超大型|Codex 最低預估呼叫數超過目前上限|優先拆分 commit 或使用本機；確認成本後才提高上限|

規模建議不是安全決策。敏感、受公司政策限制或不能送到雲端的內容，不論規模都應使用本機 `git ac`。

### 不只看行數的例外

- Lockfile、minified 與二進位檔不會展開完整內容，行數大不一定增加模型負擔。
- Snapshot、fixture 與自動產生資料資訊密度較低，可考慮獨立 commit。
- 跨模組 rename 或架構重構即使行數不大，也需要理解更多檔案關聯；非敏感時可偏向 `git ac -c`。
- 大型 JSON 或 SQL 可能行數少但單行很長，此時 map chunk 數比行數可靠。
- 混合多個變更目的時，即使模型能處理，也應先拆成多個明確 commit。

## Preview 預覽模式

```sh
git ac -p
git ac -c -p
```

`-p` 會呼叫模型、產生並驗證完整 commit message，將訊息輸出到 stdout，但不建立 commit，也不改變真實 index。沒有 staged 內容時，會使用隔離的暫存 index 模擬 `git add -A`。

範例：

```text
目前沒有 staged 變更；以下以暫存 index 模擬 git add -A，真實 index 不會改變。

納入 AI 完整 diff 分析的檔案（2）：
  M "src/app.py"
  A "tests/test_app.py"

預估模型呼叫：1 次 final。
模型呼叫次數：1

feat(app): 新增使用者設定驗證
```

檔案清單、模型資訊與進度輸出到 stderr，commit message 輸出到 stdout，方便導向其他指令而不被診斷資訊污染。

## 納入與排除 AI 分析的內容

一般文字程式碼、測試及文件會提供完整 diff。以下只提供路徑、Git 狀態與排除原因：

- 刪除檔案。
- 已知 lockfile 或檔名以 `.lock` 結尾的檔案。
- Minified JavaScript／CSS 類檔案。
- Git 判定的二進位檔案。

模型執行或估算前會分組列出：

```text
納入 AI 完整 diff 分析的檔案（3）：
  M "src/app.py"
  A "src/config.py"
  M "tests/test_app.py"

排除完整內容、只提供狀態與路徑的檔案（2）：
  M "package-lock.json"（lockfile）
  D "src/legacy.py"（刪除檔案）
```

每組最多顯示 100 筆，超出時會列出省略數量。

## 小型與大型 diff 的模型流程

工具內部的單次 prompt 上限為 48,000 UTF-8 bytes。這只限制模型輸入；建議的本機 `max_tokens: 1024` 則限制每一次 map、reduce 或 final 的輸出，兩者互不取代。

可直接放入 final 時只呼叫一次：

```text
Git diff → final → commit message
```

內容過大時：

```text
Git diff
    ↓
多個 map chunks
    ↓
各 chunk 產生摘要
    ↓
必要時進行 reduce
    ↓
final commit message
```

最低呼叫次數是 `map chunk 數 + 1 次 final`：

|處理計畫|最低模型呼叫數|
|---|---|
|直接 final|1|
|2 map + final|3|
|4 map + final|5|
|7 map + final|8|
|11 map + final|12|

如果 map 摘要合併後仍過大，還會增加 reduce 呼叫，所以估算顯示的是「至少」呼叫次數。每次本機 map、reduce 與 final 都會使用相同的 `git-ac` model ID。

## 本機與 Codex 的選擇

|考量|`git ac` 本機|`git ac -c` Codex|
|---|---|---|
|隱私|diff 留在本機|完整分析 diff 會送至 Codex|
|速度|大型異動可能較慢|大型異動通常較快|
|Codex 額度|不使用|會使用 request／額度|
|模型|預設 `mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac`|預設 `gpt-5.3-codex-spark`|
|Thinking|git 專用 profile 關閉|由 Codex 模型管理|
|建議單次輸出上限|1,024 tokens|由 Codex CLI／模型管理|
|呼叫次數上限|不設 request 上限|預設最多 12 次|
|代理工具|不適用|關閉 shell、網路搜尋、子代理、apps、plugins、hooks、瀏覽器、Computer Use 與圖片生成|

不論規模，只要內容敏感或不能離開本機就不要使用 `-c`。

## 環境變數

|環境變數|預設值|用途|
|---|---|---|
|`DEFAULT_GIT_AC_LOCAL_MODEL`|`omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac`|覆寫單次本機 `aitext` model ID|
|`GIT_AC_CODEX_MODEL`|`gpt-5.3-codex-spark`|覆寫單次 Codex model|
|`GIT_AC_CODEX_MAX_CALLS`|`12`|設定單次 Codex 執行最多模型呼叫數；必須是正整數|
|`GIT_AC_MODEL_TIMEOUT`|`120`|每一次模型呼叫的 timeout 秒數；必須是正整數|
|`GIT_AC_TRACE_FILE`|未設定|寫入權限為 `0600` 的 JSONL 驗收 trace|
|`GIT_AC_TRACE_CASE`|空字串|替 trace event 加入案例名稱|

空白的 model 環境變數會直接報錯，不會退回其他模型。

使用範例：

```sh
DEFAULT_GIT_AC_LOCAL_MODEL=omlx:custom-model git ac -p
GIT_AC_CODEX_MODEL=gpt-5.6-luna git ac -c
GIT_AC_CODEX_MAX_CALLS=20 git ac -c
GIT_AC_MODEL_TIMEOUT=300 git ac
```

timeout 套用於每一次模型呼叫，不是整次命令總時間。提高 Codex request 上限也不是固定 token 或金額保證；超大型異動通常應優先拆分。

### Codex 呼叫上限

`git ac -c` 預設最多呼叫 Codex 12 次。大型 diff 會在第一個 request 前計算 map chunks 與 final 的最低呼叫數；超過上限會直接中止，不消耗模型 request，staged snapshot 保持不變。

12 次在摘要可直接進入 final 的一般情況下，約可容納 11 個 map chunks，也就是約 500 KB 文字 diff；實際大小受檔案邊界、UTF-8 bytes 與摘要長度影響。執行中若 recursive reduce 使呼叫數達到上限，也會停止並保留 staged 內容。

確認要處理更大 diff 時才提高：

```sh
GIT_AC_CODEX_MAX_CALLS=20 git ac -c
```

## 本機 aichat／aitext／oMLX 設定

### 三個元件的責任

- [oMLX](https://github.com/jundot/omlx) 載入 Apple Silicon 上的本機模型，並提供 `http://localhost:8000/v1` OpenAI-compatible API。
- [`aichat`](https://github.com/sigoden/aichat) 讀取 client／model 設定，把 `git-ac` 的 prompt 傳給 oMLX，並串流回傳模型輸出。
- `aitext` 是本專案放在 `src/aitext` 的 Bash wrapper。它把參數與 stdin 原樣交給 `aichat`、移除串流中的 `<think>...</think>`、避免無輸入時意外進入 REPL、保留 `aichat` exit code，並把輸出結尾正規化為單一換行。它不保存 API endpoint、模型或憑證。

`git ac` 固定執行以下命令，因此不會改變平常直接使用 `aichat` 或 `aitext` 時的預設模型：

```sh
aitext -m omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac
```

### 1. 準備 oMLX 與 git-ac profile

依 [oMLX 官方安裝說明](https://github.com/jundot/omlx#install) 安裝 macOS App，或使用 Homebrew：

```sh
brew tap jundot/omlx https://github.com/jundot/omlx
brew install omlx
brew services start omlx
```

在 oMLX 下載 `mlx-community/gemma-4-26B-A4B-it-qat-4bit`，確認 API 位於 `http://localhost:8000/v1`，並建立 `git-ac` profile：

|設定|建議值|
|---|---|
|模型類型|自動偵測|
|Reasoning Parser|`None`|
|CTX WINDOW|131,072|
|最大 TOKEN 數|1,024|
|溫度|0|
|TOP P／TOP K／MIN P|0.95／64／0|
|重複懲罰／Presence Penalty|1／0|
|啟用思考|關閉|
|思考 Token 限制|關閉|
|Guided Grammar|關閉|
|限制工具回傳 Token 數|關閉；`git ac` 不使用 tool calls|
|強制取樣|關閉|

profile 名稱本身不會自動關閉 thinking 或套用取樣參數，以上數值仍須在 oMLX 儲存。temperature 為 0 時，top-p、top-k 與 min-p 的影響有限，可維持模型原值。

TTL 只控制模型閒置多久後卸載，不限制單次推論。沿用全域 1,800 秒可減少短時間重複載入；若希望更快釋放模型記憶體，可在 `git-ac` profile 改為 60～300 秒。

### 2. 安裝並設定 aichat

依 [`aichat` 官方說明](https://github.com/sigoden/aichat#install) 安裝；macOS 可使用：

```sh
brew install aichat
aichat --version
```

用以下命令確認實際設定檔位置；macOS 預設是 `~/Library/Application Support/aichat/config.yaml`：

```sh
aichat --info | rg 'config_file'
```

將以下 `omlx` client 合併到既有 `config.yaml` 的 `clients` 清單，不要覆寫其他 client 或個人設定。若 oMLX 啟用了 API key，另依 `aichat` 官方機密管理方式設定，不要把 key 寫進本 repository。

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

設定意義：

- `max_input_tokens: 131072` 記錄模型 context 能力；`git ac` 每次 prompt 另受 48,000 UTF-8 bytes 限制。
- `max_output_tokens: 1024` 供 `aichat` 記錄模型輸出能力及計算 context。
- `patch...body.max_tokens: 1024` 才會真正加入 OpenAI-compatible request。
- `temperature: 0` 降低 commit message 與 chunk 摘要的隨機性。

在已驗收的 `aichat 0.30.0` 中，只設定 `max_output_tokens` 不會自行傳送 `max_tokens`。oMLX log 應顯示：

```text
max_tokens=1024, request_max_tokens=1024
```

先直接驗證 `aichat` 能連到 profile；這一步會執行一次本機推論：

```sh
printf '只輸出：本機模型設定成功\n' | \
  aichat -m omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac
```

### 3. 安裝 aitext wrapper

`aichat` 驗證成功後，在本 repository 根目錄執行獨立設定腳本：

```sh
./scripts/setup-aitext.sh install
exec zsh
./scripts/setup-aitext.sh check
```

腳本會確認 macOS、`aichat`、Bash 與 Perl 可用，將 `src/aitext` 安裝成 `$HOME/bin/aitext`，並共用 `setup-git-ac.sh` 的 `~/.zshrc` PATH 管理區塊。它不會修改 `aichat` config、oMLX profile 或模型檔案。

|參數|行為|
|---|---|
|`install`|首次安裝 wrapper 並補上 PATH 管理區塊；預設動作|
|`update`|以 repository 的 `src/aitext` 明確更新既有 `$HOME/bin/aitext`|
|`check`|檢查依賴、來源一致性、PATH 區塊與 `aitext --version`|
|`help`、`-h`、`--help`|顯示設定腳本說明|

若 `$HOME/bin/aitext` 已存在且內容不同，`install` 會在修改 `.zshrc` 前中止，不會覆寫；先自行備份或確認該檔案可移除。日後 repository 更新 wrapper 時執行：

```sh
./scripts/setup-aitext.sh update
./scripts/setup-aitext.sh check
```

### 4. 驗證完整本機路徑

第一個命令會經過 `aitext` → `aichat` → oMLX；接著在有 staged 測試變更的 Git repository 執行預覽，驗證 `git-ac` 整合。兩者都會執行本機推論：

```sh
printf '只輸出：aitext 設定成功\n' | \
  aitext -m omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac
git ac -p
```

完成一次本機呼叫後可檢查：

```sh
rg 'Chat completion:' ~/.omlx/logs/server.log | tail -1
```

若看到 `request_max_tokens=None`，代表 request patch 尚未套用；此時 oMLX 仍會使用 model profile 的 Max Tokens。

## 失敗與安全行為

以下情況會中止 commit：

- 模型逾時、失敗或回傳空內容。
- commit message 不符合允許的 Conventional Commits 格式。
- Codex 呼叫達到上限。
- 模型處理期間 staged snapshot 被其他程序改變。
- `git commit` 執行失敗。

大部分失敗情況不會建立 commit，staged 內容會保留，終端會顯示可重試指令。

### Snapshot 保護

正式 commit 模式會在模型呼叫前後比較 staged tree，避免分析內容與實際提交內容不一致。

### 暫存 index 隔離

無 staged 的 `-p`／`-e` 使用暫存 `GIT_INDEX_FILE`、暫存 `GIT_OBJECT_DIRECTORY`，並以原 repository object database 作為唯讀 alternate，因此不會改變真實 index，也不會在專案 object database 留下暫存 blob 或 tree。

### Codex 啟動防護

Codex 後端使用權限為 `0700` 的隔離暫存 repository。每次 request 都固定帶入以下設定，不讀取使用者 Codex 設定或 execpolicy rules：

```text
--strict-config
--ignore-rules
--ephemeral
--ignore-user-config
--sandbox read-only
-c 'approval_policy="never"'
-c 'web_search="disabled"'
--disable shell_tool
--disable shell_snapshot
--disable multi_agent
--disable apps
--disable plugins
--disable hooks
--disable browser_use
--disable computer_use
--disable image_generation
```

- `--strict-config` 讓不支援的設定直接失敗，避免升級後靜默忽略安全參數。
- `--ignore-user-config` 與 `--ignore-rules` 避免個人設定、MCP、plugin 或 execpolicy 改變非互動執行。
- `--sandbox read-only` 禁止模型產生的命令寫入檔案或啟用命令網路存取。
- `approval_policy="never"` 不允許流程等待或取得額外核准。
- `web_search="disabled"` 與各項 `--disable` 移除和產生 commit message 無關的代理能力。

這是針對已驗證 Codex CLI flags 的 denylist，不是協定層 `tools=[]` 的形式化保證。升級 Codex CLI 後應重新執行整合測試，確認沒有 `command_execution`、`file_change`、`mcp_tool_call` 或 `web_search` event。

以上防護不會讓資料留在本機：完整分析 diff 仍會送至 Codex。敏感內容仍應使用本機 `git ac`。

### Commit message 暫存檔與 trace

commit message 暫存檔權限為 `0600`，使用完會刪除。

設定 `GIT_AC_TRACE_FILE` 後，工具會寫入權限為 `0600` 的 JSONL 驗收紀錄。紀錄只包含 backend、model、stage、prompt/output byte 數、`FACT_` 驗收標記、耗時與成功狀態，不包含 prompt、diff 或完整模型輸出。

## 操作範例

### 全部異動的小型修正

```sh
git ac -e
git ac
```

### 全部異動的中大型功能

```sh
git ac -e
git ac -c
```

### 先預覽再決定

```sh
git ac -e
git ac -p
```

如果預覽結果可以接受，再執行 `git ac`。這會重新呼叫模型並產生正式訊息。

### 敏感的大型異動

```sh
git ac -e
GIT_AC_MODEL_TIMEOUT=300 git ac
```

### 只處理特定模組

```sh
git add src/auth tests/auth
git ac -e
git ac -c
```

其餘 unstaged／untracked 不會被加入。

### 多個獨立目的分開 commit

```sh
git add src/auth tests/auth
git ac -e
git ac -c

git add src/billing tests/billing
git ac -e
git ac -c
```

## 開發與測試

同步依賴：

```sh
uv sync
```

所有測試 repository、暫存檔與輸出都必須放在 `.test-workspace/`。完整離線測試使用 fake `aitext`／`codex`，不連線或消耗模型額度：

```sh
mkdir -p .test-workspace/tmp .test-workspace/uv-cache
TMPDIR="$PWD/.test-workspace/tmp" \
  UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
  uv run python -m unittest discover -s tests -v
```

手動測試也不得直接操作本專案的 index 或 commit；請在 `.test-workspace` 建立隔離 repository：

```sh
repo_root="$PWD"
manual_repo="$repo_root/.test-workspace/manual"
mkdir -p "$manual_repo"
git -C "$manual_repo" init
git -C "$manual_repo" config user.name "git-ac test"
git -C "$manual_repo" config user.email "git-ac-test@example.invalid"
printf 'example\n' > "$manual_repo/example.txt"

cd "$manual_repo"
python3 "$repo_root/src/git_ac.py" -e
```

真實本機小型預覽驗收只有在明確需要時才啟用：

```sh
mkdir -p .test-workspace/tmp .test-workspace/uv-cache
TMPDIR="$PWD/.test-workspace/tmp" \
  UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
  GIT_AC_RUN_LOCAL_INTEGRATION=1 \
  uv run python -m unittest tests.test_real_integration -v
```

真實大型測試的輸出也必須指定在 `.test-workspace`：

```sh
TMPDIR="$PWD/.test-workspace/tmp" \
  UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
  uv run python tests/run_real_codex_compare.py \
  --target-kb 180 \
  --output .test-workspace/codex-compare.json

TMPDIR="$PWD/.test-workspace/tmp" \
  UV_CACHE_DIR="$PWD/.test-workspace/uv-cache" \
  uv run python tests/run_real_local_large.py \
  --target-kb 150 \
  --output .test-workspace/local-large.json
```

### 發行驗收政策

1. 每次共用流程變更先通過完整離線單元、fake 後端、150 KB 單檔與 1 MB 多檔案例；所有大型案例都必須保持 staged snapshot 並只建立一個 commit。
2. 發行本機後端前，另以真實 `aitext` → `aichat` → oMLX 驗證小型 preview／commit、大型多層彙整及排除內容；fake `aitext` 只能證明 orchestration，不能取代這一層。
3. 發行 Codex 後端前，以合成資料驗證真實 `codex exec`、呼叫上限、隔離參數與單一 commit；日常離線測試不得消耗 Codex 額度。
4. 變更 Codex 預設模型前，使用至少 20 個具 ground truth 的案例，每個模型各執行 3 次。硬性門檻為格式通過率 100%、breaking change 判定 100%、必要事實涵蓋率至少 95%、虛構事實 0，且所有大型案例只建立一個 commit。
5. 模型選擇是版本化的整體決策，不依單一 diff 臨時切換。候選模型只有在通過所有硬性門檻，且必要事實涵蓋率和對照模型差距不超過 2 個百分點時，才可成為預設。

真實後端具有非決定性，驗收應記錄日期、模型 slug、CLI／`aichat` 版本、案例、耗時與結果，不以單一參考句做完全相等比較。

每次修改 `src/git_ac.py`、`src/aitext` 或設定腳本都必須檢查本 README；只要參數、環境變數、輸出、前置需求、staging 邊界、安裝／更新、錯誤行為或使用流程有變動，就要在同一個變更中同步更新。README 是唯一的使用者文件，不另建 `docs/` 或獨立 usage guide。

## 已完成的驗收參考

以下是 2026-07-22 的既有案例，適合作為回歸參考，不是固定效能保證：

|案例|結果|
|---|---|
|本機 oMLX 小型 preview|成功產生合法訊息，沒有建立 commit，staged tree 未變|
|Codex Spark commit|成功建立且只建立一個 commit，commit tree、index tree 與執行前 staged tree 一致|
|本機 154,892-byte staged diff|4 map + 1 final，約 100.3 秒，最大 prompt 47,345 bytes，staged snapshot 未變|
|Codex Spark 185,258-byte staged diff|4 map + 1 final，約 34.3 秒，必要標記範圍保留完整|
|Codex Luna 相同大型案例|4 map + 1 final，約 41.1 秒，訊息合法但 final 過度壓縮|
|超過 1 MB 離線案例|在 48,000-byte production budget 下通過至少兩層 recursive reduce|

Spark／Luna 大型比較當時每個模型只有一個案例，不能取代多案例、多次重跑的正式品質評測；日常仍以當次 `git ac -e` 結果與資料敏感性為準。
