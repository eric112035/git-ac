#!/bin/zsh

set -eu

readonly SCRIPT_DIR="${0:A:h}"
readonly SOURCE_FILE="${SCRIPT_DIR}/../src/git_ac.py"
readonly BIN_DIR="${HOME}/bin"
readonly TARGET_FILE="${BIN_DIR}/git-ac"
readonly ZSHRC_FILE="${HOME}/.zshrc"
readonly ALIAS_VALUE='!git-ac'
readonly PATH_BLOCK_BEGIN='# >>> git-ac setup >>>'
readonly PATH_BLOCK_END='# <<< git-ac setup <<<'

usage() {
  cat <<'EOF'
用法：./scripts/setup-git-ac.sh [install|update|check|help]

  install  安裝或重新安裝 ~/bin/git-ac，設定 ~/.zshrc 與全域 alias.ac（預設）
  update   只以目前 src/git_ac.py 更新 ~/bin/git-ac
  check    檢查執行檔、~/.zshrc、全域 alias.ac 與 help
  help     顯示此說明
EOF
}

fail() {
  print -u2 -r -- "setup-git-ac: $1"
  exit 1
}

require_macos_tools() {
  [[ "$(uname -s)" == "Darwin" ]] || fail "此設定腳本只支援 macOS。"
  command -v git >/dev/null 2>&1 || fail "找不到 git；請先完成 Git 前置設定。"
  command -v python3 >/dev/null 2>&1 || fail "找不到 python3；git-ac 需要 Python 3.11 以上。"
  command -v zsh >/dev/null 2>&1 || fail "找不到 zsh。"
  [[ -f "${SOURCE_FILE}" ]] || fail "找不到來源檔：${SOURCE_FILE}"
}

python_version_is_supported() {
  python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
}

current_alias() {
  git config --global --get alias.ac 2>/dev/null || true
}

ensure_alias_is_safe() {
  local existing_alias
  existing_alias="$(current_alias)"
  if [[ -n "${existing_alias}" && "${existing_alias}" != "${ALIAS_VALUE}" ]]; then
    fail "全域 alias.ac 已存在且不是 ${ALIAS_VALUE}；為避免覆寫，請先自行更名或移除既有 alias。"
  fi
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

install_binary() {
  mkdir -p "${BIN_DIR}"
  /usr/bin/install -m 755 "${SOURCE_FILE}" "${TARGET_FILE}"
}

install_all() {
  ensure_alias_is_safe
  ensure_path_config
  install_binary
  git config --global alias.ac "${ALIAS_VALUE}"

  print -r -- "安裝完成：${TARGET_FILE}"
  print -r -- "已設定：${ZSHRC_FILE}（${BIN_DIR} 加入 PATH）"
  print -r -- "已設定：git config --global alias.ac '${ALIAS_VALUE}'"
  print -r -- "請執行 exec zsh，再以 git ac -h 驗證。"
}

update_binary() {
  [[ -e "${TARGET_FILE}" ]] || fail "尚未安裝 ${TARGET_FILE}；請先執行 install。"
  install_binary
  print -r -- "更新完成：${SOURCE_FILE} -> ${TARGET_FILE}"
}

check_installation() {
  local existing_alias
  [[ -x "${TARGET_FILE}" ]] || fail "${TARGET_FILE} 不存在或不可執行。"
  [[ -f "${ZSHRC_FILE}" ]] || fail "找不到 ${ZSHRC_FILE}。"
  path_block_is_valid || fail "${ZSHRC_FILE} 缺少完整且唯一的 git-ac PATH 管理區塊。"
  existing_alias="$(current_alias)"
  [[ "${existing_alias}" == "${ALIAS_VALUE}" ]] || fail "全域 alias.ac 未設定為 ${ALIAS_VALUE}。"
  "${TARGET_FILE}" -h >/dev/null
  PATH="${BIN_DIR}:${PATH}" git ac -h >/dev/null

  print -r -- "檢查完成：git-ac 執行檔、PATH 設定、Git alias 與 git ac -h 均有效。"
  if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    print -u2 -r -- "目前 shell 尚未載入 ${BIN_DIR}；請執行 exec zsh。"
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
      python_version_is_supported || fail "python3 版本過舊；git-ac 需要 Python 3.11 以上。"
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac

  case "${action}" in
    install) install_all ;;
    update) update_binary ;;
    check) check_installation ;;
  esac
}

main "$@"
