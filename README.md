# git-ac

`git ac` 會分析 Git staged snapshot 或目前 `HEAD` commit 的 diff，產生一則繁體中文、符合 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) 的 commit message，並建立單一 commit 或只改寫目前 commit 的訊息。

> **平台限制：** 目前僅支援並驗證 macOS 與 zsh。Linux、Windows 及其他 shell 尚不在支援範圍。

完整的安裝、設定、CLI、安全邊界、疑難排解與開發文件請見 [git-ac Wiki](https://github.com/eric112035/git-ac/wiki)。

## 功能摘要

- 支援 Apple Foundation Models（`afm`）、`aichat`、官方 Codex CLI 與 Claude Code CLI 四種 backend。
- 預設使用 `aichat`；backend 失敗時中止，不會自動切換服務。
- 生成提示要求保留使用者明確指定且有證據支持的名稱／編號；標題放不下時寫入 body。格式驗證通過不代表語意一定正確，可先用 `-p` 檢視。
- 尊重既有 staged 邊界；預設快速模式最多 final＋一次 repair，超量時明示代表片段與省略量。`-f` 可啟用有預算限制的完整 map-reduce。
- 可先 preview commit message，或只估算規模與最低模型呼叫數。
- 可從目前 `HEAD` 的 diff 重新產生並替換 commit message，不納入新的 staged／working tree 內容。
- 驗證 Conventional Commits 格式、繁體中文內容與 staged snapshot 一致性後才 commit。
- 首次格式驗證失敗時，會由相同 backend／model 依原始證據自動重產一次；仍不合格就安全中止。
- aichat／AFM 的 map、reduce 批次逾時時，只拆小失敗批次重試一次；最後仍只建立一個 commit。

## 前置條件

- macOS 與 zsh；目前不支援 Linux、Windows 或其他 shell。
- Python 3.11 以上；執行期不需要第三方 Python 套件。
- Git commit 身分已設定。
- 已準備下列其中一種 backend：

|Backend|前置需求|未設定 model 時|
|---|---|---|
|`afm`|macOS 27 內建 `fm`、已同意授權、可用的 Apple Intelligence 模型|只支援本機 `system`|
|`aichat`|已設定的 `aichat` 與本專案的 `aitext` wrapper|沿用 aichat 預設 model|
|`codex`|已安裝並登入的官方 Codex CLI|`gpt-5.6-luna`|
|`claude`|已安裝並登入的 Claude Code CLI|`haiku` alias|

```sh
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## 安裝

在本 repository 根目錄執行：

```sh
./scripts/setup-git-ac.sh install
source ~/.zshrc
git ac -h
```

腳本會安裝 `$HOME/bin/git-ac`、將 `$HOME/bin` 加入 zsh PATH，並設定：

```sh
git config --global alias.ac '!git-ac'
```

若已存在內容不同的全域 `alias.ac`，安裝會中止而不覆寫。完整行為請見 [安裝與更新](https://github.com/eric112035/git-ac/wiki/Installation-and-Update)。

安裝與更新後會檢查目前 backend；未就緒時保留安裝成果並顯示設定引導。完成下方 backend 設定後，再執行 `./scripts/setup-git-ac.sh check`；此指令會在 backend 未就緒時回傳失敗。

## 準備 backend

### Apple Foundation Models（AFM）

使用 [macOS 27 內建的官方 `fm` CLI](https://developer.apple.com/videos/play/wwdc2026/334/)，需要支援 Apple Intelligence 的 Mac，且模型已啟用並下載完成；不涵蓋所有 Mac。

```sh
fm license --status
```

若尚未同意授權，自行執行 `sudo fm license` 閱讀並同意條款。git-ac 只檢查與提示，不代為同意或執行 sudo。

```sh
git ac --backend afm config check
git ac --backend afm -p
# 確認品質適合後，明確選用：
git ac config set backend afm
```

資料只交給本機 `system` 模型，不需要 API key 或常駐 server。每批完整 prompt 以 `fm count-tokens --quiet` 確認不超過 3,000 tokens。`config check` 不產生模型回應；正式生成仍可能因系統服務或模型品質而失敗。

目前 AFM 尚未通過全部固定品質驗收，因此供明確選用，內建預設保留 aichat。只有六個案例各連續三次全部通過，才會在後續版本切換內建預設；更新不覆寫使用者既有設定。

2026-09-26 在 macOS 27 的 AFM 舊版評測為 3／18 次通過，其中小型案例將未複製 `FACT_` 字串算作事實遺漏，因此不能視為模型正確率。已確認的其他問題包括 breaking change 漏標、type 錯誤，以及約 180 KiB 大型案例三次均於約 10 分 49 秒後因 reduce 重試仍逾時而中止。新版評測改查小型案例的必要內容證據，AFM 尚未以新規則重跑。重現方式與門檻見 [架構與開發](https://github.com/eric112035/git-ac/wiki/Architecture-and-Development#afm-預設切換驗收)。

### aichat

先依 [AIChat Configuration Guide](https://github.com/sigoden/aichat/wiki/Configuration-Guide) 安裝並設定 aichat 的 client、endpoint 與 model，再安裝 `aitext`：

```sh
brew install aichat
aichat --info
aichat --list-models

./scripts/setup-aitext.sh install
./scripts/setup-aitext.sh check
git ac config set backend aichat
git ac config check
```

資料送往本機或雲端取決於 aichat 的 client／endpoint；使用 `aichat` backend 不代表資料一定留在本機。

2026-09-26～27，以 `omlx:mlx-community/gemma-4-26B-A4B-it-qat-4bit` 執行同組固定案例，未重現 AFM 的 breaking change 漏標或文件 type 錯誤。大型案例曾漏掉明確指定的編號；補強 final／repair 提示後三次均保留完整資訊且未逾時。這是固定案例的驗收結果，不代表所有變更都不會誤判；評測方式與限制見 [架構與開發](https://github.com/eric112035/git-ac/wiki/Architecture-and-Development#aichat-同組對照)。

### Codex

依 [Codex CLI 官方文件](https://learn.chatgpt.com/docs/codex/cli) 安裝並登入：

```sh
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex

git ac config set backend codex
git ac config check
```

### Claude Code

依 [Claude Code Quickstart](https://code.claude.com/docs/en/quickstart) 安裝並登入：

```sh
brew install --cask claude-code
claude

git ac config set backend claude
git ac config check
```

四種 backend 的資料流、model 覆寫與隔離方式請見 [Backend](https://github.com/eric112035/git-ac/wiki/Backends)。

## 第一次使用

進入要提交的 Git repository：

```sh
git ac config show
git ac -e
git ac -p
git ac
git ac -f -e
git ac -f -n 24 -T 600
```

- `git ac -e`：估算規模、最低模型呼叫數與條件式 repair，不呼叫模型。
- `git ac -p`：產生 preview，不建立 commit。
- `git ac`：產生訊息並建立一個 commit。

指定單次 backend、type 或參考資訊：

```sh
git ac -c -p
git ac --claude -p
git ac --backend afm -p
git ac --backend aichat -p
git ac -p -t fix
git ac -p -m "修正登入逾時，對應 issue #123"
git ac -r -p
git ac -r -t fix -m "補充原 commit 的設計理由"
```

`git ac -r` 與 `git ac --reword` 等價：兩者會分析目前 `HEAD` 相對第一個 parent 的 diff，重新產生完整訊息，再以 message-only amend 改寫該 commit。搭配 `-p` 時只預覽，搭配 `-e` 時只估算。

完整參數與設定指令請見 [CLI 參考](https://github.com/eric112035/git-ac/wiki/CLI-Reference)及[設定](https://github.com/eric112035/git-ac/wiki/Configuration)。

## Staging 與安全邊界

|執行前狀態|正式 `git ac`|`git ac -p`／`git ac -e`|
|---|---|---|
|已有 staged 變更|只分析及提交該 staged snapshot|只分析該 staged snapshot|
|沒有 staged、working tree 有異動|backend preflight 成功後執行 `git add -A`|以隔離 index 模擬 `git add -A`，真實 index 不變|
|同時有 staged 與 unstaged／untracked|只處理 staged 內容|只處理 staged 內容|

`-r／--reword` 不使用以上自動 staging 規則，而是固定分析目前 `HEAD`；目前 index 與 working tree 會被忽略並保留。Root commit 相對空 tree，merge commit 相對第一個 parent。舊 commit message 不會送給模型，需保留的理由、footer 或 issue reference 應透過 `-m` 提供。

重要邊界：

- ignored 檔案不會被加入；binary、lockfile、minified 與刪除檔案只提供狀態及路徑，不展開完整內容。
- 模型只能回傳文字，不能操作目標 repository 或呼叫工具。
- 模型處理期間 staged snapshot 改變時會中止；backend 或 commit 失敗時保留 staged 內容。
- 格式 repair 最多呼叫相同 backend／model 一次，不會把首次無效輸出交回模型或切換服務。
- Codex／Claude 的 diff 與 `--message` 會送往對應雲端；aichat 的資料去向由使用者設定決定。
- Backend 收到的是 git-ac 經 stdin 傳入的 UTF-8 純文字 prompt，不是 chat `messages` JSON；其共同結構、各階段差異與實際範例請見 Wiki。
- Reword 會建立新的 commit object 並改變 hash；若舊 commit 已推送，後續同步可能需要協調並改寫遠端歷史。git-ac 不會自動 push。

詳細流程與限制請見 [Staging 與安全邊界](https://github.com/eric112035/git-ac/wiki/Staging-and-Safety)。

## 大型變更與逾時

`git ac` 預設快速模式，不需額外參數。整理後內容能同時放入 final 與預留 repair 時全部納入；超量時 metadata 最多占可用容量四分之一且不超過 4 KiB，其餘依路徑穩定排序輪流選取各檔案首尾片段，每片最多 2 KiB。會揭露未列路徑與省略量；快速模式不保證涵蓋所有 breaking change，可用 `-p` 審視。

兩種模式保留 3 行 diff context，將超過 1 KiB、可驗證解碼的單行媒體 Base64 data URI 改成 MIME、解碼大小及 SHA-256 描述，保留新增／刪除／未變更標記。只有分析版本 `.gitattributes` 的 `linguist-generated` 為 set／true 才只提供路徑與狀態；未標記的 dist／build 手寫檔案仍分析。一般／preview 使用對應 index 屬性，reword 使用被分析 commit 屬性。

|模式／參數|行為|
|---|---|
|快速（預設）|最多 2 次生成：final＋必要時 repair；總時間 120 秒|
|`-f`／`--full`|完整可分析文字經 map-reduce，預設最多 12 次生成；總時間 300 秒|
|`-n`／`--max-calls`|完整模式正整數上限；CLI 優先於既有 Codex／Claude 上限環境變數，再採預設 12|
|`-T`／`--max-time`|兩種模式的總秒數正整數上限|

完整模式最低呼叫數（map 批次＋final）超標時，生成前中止並顯示提高預算的指令；最低值不含未知 reduce、重試與 repair。所有生成嘗試均計入上限，每輪開始前檢查已知剩餘工作，每次生成前再硬性檢查。快速模式也尊重既有更嚴格的 backend 上限。不會自動切換模式或 backend，也不提交部分結果。

aichat 每批完整 prompt 預設 24,000 UTF-8 bytes，可用 `GIT_AC_AICHAT_PROMPT_BYTES` 在 8,000–48,000 間調整；Codex／Claude 維持 48,000 bytes。AFM 使用 3,000-token 保守輸入預算，並非模型實際 context 上限。

```sh
GIT_AC_AICHAT_PROMPT_BYTES=12000 git ac --backend aichat -p
GIT_AC_MODEL_TIMEOUT=240 git ac --backend aichat -T 300 -p
```

`GIT_AC_MODEL_TIMEOUT` 預設單次 120 秒；外部程序使用既有單次 timeout 與剩餘總時間的較小值。總期限從 backend preflight 前開始，含整理、token 計數與生成，Git commit／hook 不計入。期限到期清理整組程序且不啟動拆批或 repair。完整模式的 aichat／AFM 摘要單次逾時可只拆失敗批次重試一次；final／repair 單次逾時直接中止。進度顯示原始／整理後／納入大小、各檔案原因、呼叫與耗時；preview stdout 只含訊息，診斷寫 stderr。Trace 僅記錄統計，不保存 diff、prompt 或資產本文。

`-e` 不需要可用的 `fm`，AFM 的批次數是保守估算；實際 token 檢查、reduce、拆批重試或格式 repair 都可能使呼叫數不同。

2026-10-11，以目前 Gemma 完成新模式 24／24 次合成驗收：快速模式 21 次各只呼叫一次，完整大型案例三次各呼叫 10 次。詳細案例、耗時與限制見 [模式驗收](https://github.com/eric112035/git-ac/wiki/Architecture-and-Development#快速完整模式驗收2026-10-11)。

## 更新

```sh
git pull --ff-only
./scripts/setup-git-ac.sh update
./scripts/setup-git-ac.sh check
```

若新版也修改 `src/aitext`，且你使用 aichat backend：

```sh
./scripts/setup-aitext.sh update
./scripts/setup-aitext.sh check
```

## 文件

- [快速開始](https://github.com/eric112035/git-ac/wiki/Quick-Start)
- [安裝與更新](https://github.com/eric112035/git-ac/wiki/Installation-and-Update)
- [CLI 參考](https://github.com/eric112035/git-ac/wiki/CLI-Reference)
- [設定](https://github.com/eric112035/git-ac/wiki/Configuration)
- [Backend](https://github.com/eric112035/git-ac/wiki/Backends)
- [Staging 與安全邊界](https://github.com/eric112035/git-ac/wiki/Staging-and-Safety)
- [疑難排解](https://github.com/eric112035/git-ac/wiki/Troubleshooting)
- [架構與開發](https://github.com/eric112035/git-ac/wiki/Architecture-and-Development)

## License

[MIT](LICENSE)
