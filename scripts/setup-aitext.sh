#!/bin/zsh

set -eu

readonly SCRIPT_DIR="${0:A:h}"
readonly SOURCE_FILE="${SCRIPT_DIR}/../src/aitext"
readonly BIN_DIR="${HOME}/bin"
readonly TARGET_FILE="${BIN_DIR}/aitext"
readonly ZSHRC_FILE="${HOME}/.zshrc"
readonly PATH_BLOCK_BEGIN='# >>> git-ac setup >>>'
readonly PATH_BLOCK_END='# <<< git-ac setup <<<'

usage() {
  cat <<'EOF'
用法：./scripts/setup-aitext.sh [install|update|check|help]

  install  安裝 ~/bin/aitext，並在需要時設定 ~/.zshrc（預設）
  update   以目前 src/aitext 更新既有 ~/bin/aitext
  check    檢查 aichat、aitext、Perl、~/.zshrc 與 wrapper 版本呼叫
  help     顯示此說明

執行前請先依 README 安裝及設定 aichat 與本機模型服務。
EOF
}

fail() {
  print -u2 -r -- "setup-aitext: $1"
  exit 1
}

require_macos_tools() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "此設定腳本只支援 macOS。"
  command -v aichat >/dev/null 2>&1 || fail "找不到 aichat；請先依 README 完成安裝與設定。"
  command -v bash >/dev/null 2>&1 || fail "找不到 bash。"
  command -v perl >/dev/null 2>&1 || fail "找不到 perl；aitext 需要 Perl 進行串流輸出過濾。"
  command -v zsh >/dev/null 2>&1 || fail "找不到 zsh。"
  command -v cmp >/dev/null 2>&1 || fail "找不到 cmp。"
  [[ -f "${SOURCE_FILE}" ]] || fail "找不到來源檔：${SOURCE_FILE}"
}

path_block_is_valid() {
  local begin_count end_count
  begin_count="$(grep -Fxc -- "${PATH_BLOCK_BEGIN}" "${ZSHRC_FILE}" 2>/dev/null || true)"
  end_count="$(grep -Fxc -- "${PATH_BLOCK_END}" "${ZSHRC_FILE}" 2>/dev/null || true)"
  begin_count="${begin_count:-0}"
  end_count="${end_count:-0}"
  [[ "${begin_count}" == "1" && "${end_count}" == "1" ]]
}

ensure_path_config() {
  local begin_count end_count
  begin_count="$(grep -Fxc -- "${PATH_BLOCK_BEGIN}" "${ZSHRC_FILE}" 2>/dev/null || true)"
  end_count="$(grep -Fxc -- "${PATH_BLOCK_END}" "${ZSHRC_FILE}" 2>/dev/null || true)"
  begin_count="${begin_count:-0}"
  end_count="${end_count:-0}"

  if [[ "${begin_count}" == "1" && "${end_count}" == "1" ]]; then
    return
  fi
  if [[ "${begin_count}" != "0" || "${end_count}" != "0" ]]; then
    fail "${ZSHRC_FILE} 內的 git-ac 管理區塊不完整或重複；請先修正標記後重試。"
  fi

  touch "${ZSHRC_FILE}"
  {
    print -r -- ''
    print -r -- "${PATH_BLOCK_BEGIN}"
    print -r -- 'if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then'
    print -r -- '  export PATH="$HOME/bin:$PATH"'
    print -r -- 'fi'
    print -r -- "${PATH_BLOCK_END}"
  } >> "${ZSHRC_FILE}"
}

ensure_target_is_safe() {
  if [[ ! -e "${TARGET_FILE}" && ! -L "${TARGET_FILE}" ]]; then
    return
  fi
  [[ -f "${TARGET_FILE}" && ! -L "${TARGET_FILE}" ]] || \
    fail "${TARGET_FILE} 已存在且不是一般檔案；不會覆寫。"
  source_matches_target || \
    fail "${TARGET_FILE} 已存在且內容不同；請先備份或移除，再重新執行 install。"
}

source_matches_target() {
  cmp -s "${SOURCE_FILE}" "${TARGET_FILE}" || \
    [[ "$(<"${SOURCE_FILE}")" == "$(<"${TARGET_FILE}")" ]]
}

install_wrapper() {
  mkdir -p "${BIN_DIR}"
  /usr/bin/install -m 755 "${SOURCE_FILE}" "${TARGET_FILE}"
}

install_all() {
  ensure_target_is_safe
  ensure_path_config
  install_wrapper

  print -r -- "安裝完成：${TARGET_FILE}"
  print -r -- "已確認：aichat 與 Perl 可執行"
  print -r -- '請在目前終端執行 source ~/.zshrc（或 exec zsh），再以 ./scripts/setup-aitext.sh check 驗證。'
}

update_wrapper() {
  [[ -f "${TARGET_FILE}" && ! -L "${TARGET_FILE}" ]] || \
    fail "尚未安裝一般檔案 ${TARGET_FILE}；請先執行 install。"
  install_wrapper
  print -r -- "更新完成：${SOURCE_FILE} -> ${TARGET_FILE}"
}

check_installation() {
  [[ -x "${TARGET_FILE}" && ! -L "${TARGET_FILE}" ]] || \
    fail "${TARGET_FILE} 不存在、不可執行或不是一般檔案。"
  [[ -f "${ZSHRC_FILE}" ]] || fail "找不到 ${ZSHRC_FILE}。"
  path_block_is_valid || fail "${ZSHRC_FILE} 缺少完整且唯一的 git-ac PATH 管理區塊。"
  source_matches_target || \
    fail "${TARGET_FILE} 與目前 repository 的 src/aitext 不一致；請執行 update。"
  "${TARGET_FILE}" --version >/dev/null

  print -r -- "檢查完成：aichat、aitext wrapper、Perl 與 PATH 設定均有效。"
  if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    print -u2 -r -- "目前 shell 尚未載入 ${BIN_DIR}；請執行 source ~/.zshrc（或 exec zsh）。"
  fi
}

main() {
  local action="${1:-install}"
  [[ "$#" -le 1 ]] || {
    usage >&2
    exit 2
  }

  case "${action}" in
    help|-h|--help)
      usage
      return
      ;;
    install|update|check)
      require_macos_tools
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac

  case "${action}" in
    install) install_all ;;
    update) update_wrapper ;;
    check) check_installation ;;
  esac
}

main "$@"
