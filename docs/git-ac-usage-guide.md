## 1. 功能定位

`git ac` 依 Git 變更產生一則繁體中文、符合 Conventional Commits 1.0.0 的 commit message，並建立單一 commit。

它提供兩個模型後端：

- `git ac`：使用本機 `aitext`／oMLX，預設指定 `mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac` profile。
- `git ac -c`：使用官方 Codex CLI，預設模型為 `gpt-5.3-codex-spark`。

兩個後端共用相同的 staged 邊界、排除規則、大型 diff 分塊、訊息格式驗證與 snapshot 安全檢查。

主要差異是隱私、速度及 Codex 額度成本。

## 2. 建議的日常流程

想估算目前所有尚未提交的變更，可以直接執行：

```
git ac -e
```

不需要先執行 `git add`。

如果只想分析特定 commit 範圍，才需要先 staging：

```
git add <這次要提交的檔案>
git ac -e
```

最後依估算結果選擇：

```
git ac       # 本機模型並建立 commit
git ac -c    # Codex Spark 並建立 commit
```

如果只想先看 commit message：

```
git ac -p       # 本機預覽
git ac -c -p    # Codex 預覽
```

同樣不需要先執行 `git add`。

最簡單的日常流程是：

```
git ac -e
    ↓
小型或敏感內容 → git ac
中大型且非敏感 → git ac -c
超大型 → 先拆分 commit
```

## 3. `-e` 估算模式

日常使用短參數：

```
git ac -e
```

也支援完整名稱：

```
git ac --estimate
```

估算模式會使用正式執行的同一套：

- 檔案納入及排除規則
- diff 組裝方式
- prompt 大小限制
- map chunk 規劃
- Codex 呼叫上限

但它不會：

- 呼叫本機模型。
- 呼叫 Codex。
- 建立 commit。
- 對真實 index 執行 `git add -A`。
- 改變真實 staged snapshot。
- 在專案 `.git/objects` 留下暫存物件。
- 要求 `aitext` 或 `codex` 已安裝。

`-e` 不可與 `-c` 或 `-p` 同時使用。

以下組合無效：

```
git ac -e -c
git ac -e -p
```

## 4. 沒有 staged 時如何估算

如果目前沒有 staged 內容：

```
git status --short
```

例如：

```
 M src/app.py
?? tests/test_app.py
```

直接執行：

```
git ac -e
```

工具會：

1. 建立隔離的暫存 index。
2. 建立隔離的暫存 Git object database。
3. 在暫存環境模擬 `git add -A`。
4. 分析 tracked、unstaged 與 untracked 變更。
5. 完成後刪除暫存環境。

終端會顯示：

```
目前沒有 staged 變更；以下以暫存 index 模擬 git add -A，真實 index 不會改變。
```

這不代表檔案真的被 staged。

執行後：

```
git status --short
```

仍然會維持：

```
 M src/app.py
?? tests/test_app.py
```

## 5. `-e` 輸出說明

範例：

```
目前沒有 staged 變更；以下以暫存 index 模擬 git add -A，真實 index 不會改變。

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

日常判斷以以下資訊為主：

- 完整分析檔案數
- 排除完整內容的檔案數
- 增刪行數
- map chunk 數
- 預估模型呼叫數
- 規模判定
- 本機／Codex 建議

你不需要自行計算 byte。

KiB 只作為輔助資訊，主要用來辨識：

- 大型 JSON
- 大型 SQL
- 長字串資料
- 行數不多但每行很長的內容
- 單行產生檔

## 6. 規模判斷方式

`git ac -e` 採 OR 判定，只要符合其中一項，就會提高規模等級。

|規模|判定條件|一般建議|
|---|---|---|
|小型|完整分析檔案不超過 5 個、合計不超過 300 行、可直接 final|`git ac`|
|中型|超過 5 個檔案、超過 300 行，或需要 1～3 個 map chunks|本機可處理；非敏感且重視速度可用 `git ac -c`|
|大型|超過 20 個檔案、超過 1,000 行，或至少 4 個 map chunks|非敏感內容建議 `git ac -c`|
|超大型|Codex 最低預估呼叫數超過目前上限|優先拆分 commit 或使用本機；確認成本後才提高上限|

規模建議不是安全決策。

只要內容敏感、受公司政策限制或不能送到雲端，不論規模都應使用：

```
git ac
```

## 7. 不只看行數的例外

檔案數及行數只是方便理解的近似值。以下案例要搭配 chunk 結果判斷。

### Lockfile、minified 與二進位檔案

這些檔案不會展開完整內容，因此行數很大也不一定增加模型負擔。

### Snapshot、fixture 與自動產生資料

這些內容可能有很多行，但資訊密度較低。適合考慮獨立 commit。

### 跨模組 rename 或架構重構

行數可能不大，但模型需要理解的檔案關聯很多。非敏感時可偏向：

```
git ac -c
```

### 大型 JSON 或 SQL

行數可能不多，但每行非常長。此時 map chunk 數比行數可靠。

### 混合多個變更目的

即使模型可以處理，也應優先拆成多個有明確目的的 commit。

## 8. Staging 邊界

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

```
git ac -e
git ac -p
```

這兩個指令都會用暫存 index 模擬所有變更。

後續正式執行：

```
git ac
```

才會真的執行 `git add -A` 並建立 commit。

### 只分析部分檔案

先手動 staging：

```
git add src/login.py tests/test_login.py
git ac -e
git ac
```

即使工作目錄還有其他 unstaged 或 untracked 檔案，也不會混入這次估算及 commit。

## 9. `-p` 預覽模式

本機預覽：

```
git ac -p
```

Codex 預覽：

```
git ac -c -p
```

`-p` 會：

- 呼叫模型。
- 產生完整 commit message。
- 驗證 Conventional Commits 格式。
- 將 commit message 輸出到 stdout。
- 不建立 commit。
- 不改變真實 index。

如果沒有 staged 內容，`-p` 會使用暫存 index 模擬 `git add -A`。

例如：

```
git ac -p
```

可能顯示：

```
目前沒有 staged 變更；以下以暫存 index 模擬 git add -A，真實 index 不會改變。

納入 AI 完整 diff 分析的檔案（2）：
  M "src/app.py"
  A "tests/test_app.py"

預估模型呼叫：1 次 final。
模型呼叫次數：1

feat(app): 新增使用者設定驗證
```

執行後不會 staging 或 commit。

## 10. Preview 與 Estimate 的差異

|指令|呼叫模型|建立 commit|無 staged 時|主要用途|
|---|---|---|---|---|
|`git ac -e`|否|否|暫存模擬全部變更|估算規模並選擇策略|
|`git ac -p`|本機|否|暫存模擬全部變更|預覽本機模型訊息|
|`git ac -c -p`|Codex|否|暫存模擬全部變更|預覽 Codex 訊息|
|`git ac`|本機|是|實際執行 `git add -A`|產生訊息並 commit|
|`git ac -c`|Codex|是|實際執行 `git add -A`|使用 Codex 產生訊息並 commit|

先執行 `-p` 再正式執行會呼叫模型兩次，而且兩次訊息可能略有不同。

只想判斷規模時，應使用不呼叫模型的：

```
git ac -e
```

## 11. 納入與排除 AI 分析的內容

模型執行或估算前會列出兩組檔案：

```
納入 AI 完整 diff 分析的檔案（3）：
  M "src/app.py"
  A "src/config.py"
  M "tests/test_app.py"

排除完整內容、只提供狀態與路徑的檔案（2）：
  M "package-lock.json"（lockfile）
  D "src/legacy.py"（刪除檔案）
```

一般文字程式碼、測試及文件會提供完整 diff。

以下內容只提供路徑、Git 狀態與排除原因：

- 刪除檔案
- 已知 lockfile
- 檔名以 `.lock` 結尾的檔案
- minified JavaScript／CSS 類檔案
- Git 判定的二進位檔案

每組最多列出 100 筆，超出時會顯示省略數量。

正常模型執行時，檔案清單與進度會輸出到 stderr，不會污染 `git ac -p` 的 commit message stdout。

## 12. 小型與大型 diff 的模型流程

工具內部的單次 prompt 上限為：

```
48,000 UTF-8 bytes
```

這是內部安全限制，不需要自行換算。

這個限制只計算送給模型的輸入 prompt。建議的本機 `max_tokens: 1024` 則限制每次 map、reduce 或 final 的模型輸出，不會縮短或阻止 client 傳入符合 48,000-byte budget 的 diff。

內容可以直接放入 final 時：

```
Git diff → final → commit message
```

模型只呼叫一次。

內容過大時：

```
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

最低呼叫次數為：

```
map chunk 數 + 1 次 final
```

例如：

|處理計畫|最低模型呼叫數|
|---|---|
|直接 final|1|
|2 map + final|3|
|4 map + final|5|
|7 map + final|8|
|11 map + final|12|

如果 map 摘要合併後仍過大，會增加 reduce 呼叫。

因此 `git ac -e` 顯示的是「至少」呼叫次數。

`max_tokens: 1024` 是每一次模型 request 的輸出上限，不是整次 `git ac` 共用的總額。例如 4 個 map chunks 至少會有 4 次 map 與 1 次 final，每次各自套用 1,024-token 上限。

本機大型異動的每個 map、reduce 與 final 都會明確指定同一個 `git-ac` model ID。該 profile 關閉 thinking，能避免 commit message 任務產生不必要的推理 tokens；輸出上限則防止單一摘要異常膨脹。這些設定都不會減少 map chunk 數，chunk 數仍只由輸入 prompt 的 48,000-byte budget、檔案邊界與 UTF-8 bytes 決定。

## 13. 本機與 Codex 的選擇

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

實測參考：

- 本機 oMLX：154,892-byte staged diff，4 map + 1 final，約 100.3 秒。
- Codex Spark：185,258-byte staged diff，4 map + 1 final，約 34.3 秒。
- Codex Luna：相同案例，4 map + 1 final，約 41.1 秒。

這些是已完成案例的參考，不是完全相同輸入的嚴格效能基準。日常以當次：

```
git ac -e
```

顯示的結果為準。

## 14. Codex 呼叫上限

`git ac -c` 預設最多呼叫 Codex：

```
12 次
```

如果 `git ac -e` 顯示：

```
預估模型呼叫：至少 14 次
Codex 上限：超過目前 12 次上限
規模判定：超大型
```

正式執行 `git ac -c` 時，會在第一個 Codex request 前中止：

- 不消耗模型 request。
- 不建立 commit。
- staged snapshot 保持不變。

如果初始估算在上限內，但後續 reduce 使實際呼叫達到上限，也會停止。

確認要處理更大的 diff 時，可以只對單次指令提高上限：

```
GIT_AC_CODEX_MAX_CALLS=20 git ac -c
```

提高 request 上限不是固定 token 或金額保證。超大型異動通常應優先拆成數個 commit。

## 15. 本機、Codex 模型與 timeout

### 本機預設模型

`git ac` 預設執行：

```
aitext -m omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit:git-ac
```

因此只影響 `git ac`；平常直接執行 `aitext` 仍使用 `aichat` 的全域預設模型。

預設值同時定義在程式常數 `DEFAULT_GIT_AC_LOCAL_MODEL`，也能以同名環境變數對單次執行覆寫：

```
DEFAULT_GIT_AC_LOCAL_MODEL=omlx:custom-model git ac
DEFAULT_GIT_AC_LOCAL_MODEL=omlx:custom-model git ac -p
```

空白值會中止，不會靜默退回其他模型。

### `aichat` 與 oMLX 設定

在 `aichat` 的 `omlx` client 中登錄 git 專用 profile：

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

- `max_input_tokens: 131072`：記錄模型 context 能力。`git ac` 每次 prompt 另受 48,000 UTF-8 bytes 限制，實際輸入遠低於此上限。
- `max_output_tokens: 1024`：供 `aichat` 記錄模型輸出能力及計算 context；`aichat 0.30.0` 不會只因這個欄位就傳送 `max_tokens`。
- `patch...body.max_tokens: 1024`：真正加入 OpenAI-compatible request，使 client request 與 oMLX `git-ac` profile 的 Max Tokens 1,024 保持一致。
- `temperature: 0`：降低 commit message 與 chunk 摘要的隨機性。

上述 request patch 以完整 model ID 精確比對，因此不影響 `omlx` client 的其他模型或 profile。

oMLX 的 `git-ac` profile 建議值：

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

設定檔名稱不會自動關閉 thinking 或套用取樣參數，以上數值仍須在 oMLX 儲存。temperature 為 0 時，top-p、top-k 與 min-p 的影響有限，可維持模型原值。

TTL 只控制模型閒置多久後卸載，不限制單次推論。沿用全域 1,800 秒可減少短時間內重複載入；若希望執行後更快釋放約 15.8 GB 模型記憶體，可在 `git-ac` profile 改為 60～300 秒。

完成一次本機呼叫後，可以檢查：

```
rg 'Chat completion:' ~/.omlx/logs/server.log | tail -1
```

預期包含：

```
max_tokens=1024, request_max_tokens=1024
```

若看到 `request_max_tokens=None`，代表 `aichat` request patch 尚未套用；此時 oMLX 仍會使用 model profile 的 Max Tokens。

### Codex 預設模型

`git ac -c` 預設使用：

```
gpt-5.3-codex-spark
```

暫時改用 Luna：

```
GIT_AC_CODEX_MODEL=gpt-5.6-luna git ac -c
```

目前大型案例的初步結果：

- Spark 較快。
- Spark 保留的變更細節較完整。
- Luna 也能完成相同的 chunk 流程。

因此目前維持 Spark 為預設。

### 共用 timeout

每次模型呼叫預設 timeout：

```
120 秒
```

需要延長時：

```
GIT_AC_MODEL_TIMEOUT=300 git ac
GIT_AC_MODEL_TIMEOUT=300 git ac -c
```

timeout 套用於每一次模型呼叫，不是整次命令的總時間。

## 16. 失敗與安全行為

以下情況會中止 commit：

- 模型逾時、失敗或回傳空內容。
- commit message 不符合允許的 Conventional Commits 格式。
- Codex 呼叫達到上限。
- 模型處理期間 staged snapshot 被其他程序改變。
- `git commit` 執行失敗。

### Snapshot 保護

正式 commit 模式會在模型呼叫前後比較 staged tree，避免分析內容與實際提交內容不一致。

### 暫存 index 隔離

無 staged 的 `-p`／`-e` 使用：

- 暫存 `GIT_INDEX_FILE`
- 暫存 `GIT_OBJECT_DIRECTORY`
- 原 repository object database 作為唯讀 alternate

因此不會改變真實 index，也不會在專案 object database 留下暫存 blob 或 tree。

### Codex 啟動防護

Codex 後端使用權限為 `0700` 的隔離暫存 repository。每次 `git ac -c` 的 Codex request 都固定帶入以下設定，不讀取使用者 Codex 設定或 execpolicy rules：

```
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

這組設定的作用如下：

- `--strict-config`：Codex CLI 不接受某項設定時直接失敗，避免升級後靜默忽略安全參數。
- `--ignore-user-config` 與 `--ignore-rules`：避免個人設定、MCP、plugin 或 execpolicy 改變這次非互動執行的工具與權限。
- `--sandbox read-only`：禁止模型產生的命令寫入檔案或啟用命令網路存取。
- `approval_policy="never"`：不允許非互動流程等待或取得額外核准；超出既有邊界的動作直接失敗。
- `web_search="disabled"` 與各項 `--disable`：移除目前已知且與產生 commit message 無關的代理工具能力。

這是針對已驗證 Codex CLI 功能旗標的 denylist，不是協定層 `tools=[]` 的形式化保證。升級 Codex CLI 後應重新執行整合測試與合成 request，確認沒有 `command_execution`、`file_change`、`mcp_tool_call` 或 `web_search` event。

上述防護不會讓資料留在本機：完整分析 diff 仍會作為 prompt 傳送至 Codex。敏感內容、受政策限制的內容或不能送至雲端的內容，仍應使用本機 `git ac`。

### Commit message 暫存檔

commit message 暫存檔權限為：

```
0600
```

使用完會刪除。

大部分失敗情況下：

- 不會建立 commit。
- staged 內容會保留。
- 終端會顯示可重試指令。

## 17. 安裝與全域 alias

先備份現有 alias：

```
git config --global --get alias.ac > "$HOME/.git-ac-alias.backup"
```

確認 `~/bin` 存在：

```
mkdir -p "$HOME/bin"
```

安裝目前版本：

```
install -m 755 \
  "/Users/eric/Gen AI/Project/Git Design/git-ac/src/git_ac.py" \
  "$HOME/bin/git-ac"
```

設定全域 alias：

```
git config --global alias.ac '!git-ac'
```

驗證：

```
command -v git-ac
git config --global --get alias.ac
git ac -h
```

預期 help 包含：

```
-p              只預覽訊息，不 commit 或改變真實 index
-e, --estimate  估算分析規模與模型呼叫，不呼叫模型、commit 或改變真實 index
```

如果先前已安裝舊版，重新執行 `install -m 755` 即可更新 `~/bin/git-ac`。

`install` 是常見 Unix 工具，不是 macOS 專屬命令。這裡負責複製檔案並設定 `755` 執行權限。

## 18. 操作範例

### 全部異動的小型修正

```
git ac -e
git ac
```

### 全部異動的中大型功能

```
git ac -e
git ac -c
```

### 先預覽再決定

```
git ac -e
git ac -p
```

如果預覽結果可以接受：

```
git ac
```

### 敏感的大型異動

```
git ac -e
GIT_AC_MODEL_TIMEOUT=300 git ac
```

### 只處理特定模組

```
git add src/auth tests/auth
git ac -e
git ac -c
```

其餘 unstaged／untracked 不會被加入。

### 多個獨立目的分開 commit

```
git add src/auth tests/auth
git ac -e
git ac -c

git add src/billing tests/billing
git ac -e
git ac -c
```

## 19. 最終操作原則

```
想分析全部異動
    ↓
直接 git ac -e
    ↓
依建議選擇 git ac 或 git ac -c
```

```
只想分析部分異動
    ↓
git add <檔案>
    ↓
git ac -e
    ↓
依建議選擇 git ac 或 git ac -c
```

```
只想預覽訊息
    ↓
直接 git ac -p 或 git ac -c -p
    ↓
真實 index 不會改變
```
