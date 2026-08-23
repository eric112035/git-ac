# git-ac

`git ac` 會分析 Git staged snapshot 或目前 `HEAD` commit 的 diff，產生一則繁體中文、符合 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) 的 commit message，並建立單一 commit 或只改寫目前 commit 的訊息。

> **平台限制：** 目前僅支援並驗證 macOS 與 zsh。Linux、Windows 及其他 shell 尚不在支援範圍。

完整的安裝、設定、CLI、安全邊界、疑難排解與開發文件請見 [git-ac Wiki](https://github.com/eric112035/git-ac/wiki)。

## 功能摘要

- 支援 `aichat`、官方 Codex CLI 與 Claude Code CLI 三種 backend。
- 預設使用 `aichat`；backend 失敗時中止，不會自動切換服務。
- 尊重既有 staged 邊界；大型 diff 會自動分塊並以 recursive map-reduce 處理。
- 可先 preview commit message，或只估算規模與最低模型呼叫數。
- 可從目前 `HEAD` 的 diff 重新產生並替換 commit message，不納入新的 staged／working tree 內容。
- 驗證 Conventional Commits 格式、繁體中文內容與 staged snapshot 一致性後才 commit。
- 首次格式驗證失敗時，會由相同 backend／model 依原始證據自動重產一次；仍不合格就安全中止。

## 前置條件

- macOS 與 zsh；目前不支援 Linux、Windows 或其他 shell。
- Python 3.11 以上；執行期不需要第三方 Python 套件。
- Git commit 身分已設定。
- 已準備下列其中一種 backend：

|Backend|前置需求|未設定 model 時|
|---|---|---|
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
./scripts/setup-git-ac.sh check
git ac -h
```

腳本會安裝 `$HOME/bin/git-ac`、將 `$HOME/bin` 加入 zsh PATH，並設定：

```sh
git config --global alias.ac '!git-ac'
```

若已存在內容不同的全域 `alias.ac`，安裝會中止而不覆寫。完整行為請見 [安裝與更新](https://github.com/eric112035/git-ac/wiki/Installation-and-Update)。

## 準備 backend

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

三種 backend 的資料流、model 覆寫與隔離方式請見 [Backend](https://github.com/eric112035/git-ac/wiki/Backends)。

## 第一次使用

進入要提交的 Git repository：

```sh
git ac config show
git ac -e
git ac -p
git ac
```

- `git ac -e`：估算規模、最低模型呼叫數與條件式 repair，不呼叫模型。
- `git ac -p`：產生 preview，不建立 commit。
- `git ac`：產生訊息並建立一個 commit。

指定單次 backend、type 或參考資訊：

```sh
git ac -c -p
git ac --claude -p
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
