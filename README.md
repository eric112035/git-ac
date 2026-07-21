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

以相同的大型合成 staged diff 比較真實 Spark 與 Luna，並只保存 stage metrics：

```sh
uv run python tests/run_real_codex_compare.py --target-kb 180
```

可設定 `GIT_AC_TRACE_FILE` 寫入權限為 `0600` 的 JSONL 驗收紀錄。紀錄只包含 backend、model、stage、prompt/output byte 數、`FACT_` 驗收標記、耗時與成功狀態，不包含 prompt、diff 或完整模型輸出。
