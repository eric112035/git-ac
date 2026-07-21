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

一般測試只使用 `tests/fakes/bin` 的假後端，不會連線或消耗模型額度。尚未完成真實 `aitext`／oMLX、真實 Codex 與 Spark／Luna 固定評測集驗收前，不應安裝到 `~/bin/git-ac`。

真實本機小型預覽驗收需明確啟用：

```sh
GIT_AC_RUN_LOCAL_INTEGRATION=1 uv run python -m unittest tests.test_real_integration -v
```
