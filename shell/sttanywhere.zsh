# Optional Zsh/ZLE adapter. Source from an interactive Zsh configuration.
# The current command line is only edited; this adapter never accepts it.
[[ -o interactive ]] || return 0
[[ -n ${STTANYWHERE_ZSH_ADAPTER_LOADED-} ]] && return 0
STTANYWHERE_ZSH_ADAPTER_LOADED=1

zmodload zsh/net/socket 2>/dev/null || return 0
zmodload zsh/stat 2>/dev/null || true

_sttanywhere_runtime=${STTANYWHERE_RUNTIME_DIR:-/tmp/sttanywhere-${UID}}
_sttanywhere_runtime=${_sttanywhere_runtime%/}
_sttanywhere_pid=$$
_sttanywhere_sock="${_sttanywhere_runtime}/shell-${_sttanywhere_pid}.sock"
_sttanywhere_registry="${_sttanywhere_runtime}/shell-${_sttanywhere_pid}.json"
_sttanywhere_marker='(Recording....) '
_sttanywhere_saved_marker=''
_sttanywhere_saved_offset=-1
_sttanywhere_socket_fd=-1

_sttanywhere_start_token() {
  local statline rest
  [[ -r /proc/${_sttanywhere_pid}/stat ]] || return 1
  IFS= read -r statline < /proc/${_sttanywhere_pid}/stat || return 1
  # comm is parenthesized and may contain spaces; fields after its final ')' start at field 3.
  rest=${statline##*) }
  local -a fields
  fields=( ${(z)rest} )
  print -r -- "${fields[20]}"
}

_sttanywhere_check_runtime() {
  python3 - "$_sttanywhere_runtime" <<'PYRUNTIME'
import os, stat, sys
p = sys.argv[1]
st = os.lstat(p)
if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
    raise SystemExit("STT Anywhere runtime directory is not private and owned by this user")
PYRUNTIME
}

_sttanywhere_register() {
  local token ttypath window old_umask
  old_umask=$(umask)
  umask 077
  token=$(_sttanywhere_start_token) || { umask "$old_umask"; return 1; }
  ttypath=${TTY:-$(tty 2>/dev/null)}
  window=${WINDOWID:-}
  python3 - "$_sttanywhere_registry" "$_sttanywhere_pid" "$token" "$ttypath" "$window" <<'PY'
import json, os, sys, tempfile
path, pid, token, tty, window = sys.argv[1:]
record = {'pid': int(pid), 'process_token': token, 'tty': tty, 'window_id': window or None}
fd, tmp = tempfile.mkstemp(prefix='.shell-registry-', dir=os.path.dirname(path))
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(record, f, separators=(',', ':'))
        f.write('\n')
    os.replace(tmp, path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
PY
  chmod 600 -- "$_sttanywhere_registry" 2>/dev/null || true
  umask "$old_umask"
}

_sttanywhere_remove_registry() {
  rm -f -- "$_sttanywhere_registry" "$_sttanywhere_sock"
}

_sttanywhere_reply() {
  local fd=$1 data=$2
  print -r -u "$fd" -- "$data"
  exec {fd}>&- 2>/dev/null || true
}

_sttanywhere_rpc_handler() {
  local listener=$1 conn request
  zsocket -a -t "$listener" 2>/dev/null || return 0
  conn=$REPLY
  [[ -n $conn ]] || return 0
  IFS= read -r -t 0.25 -u "$conn" request || { exec {conn}>&-; return 0; }
  _sttanywhere_pending_conn=$conn
  _sttanywhere_pending_request=$request
  zle _sttanywhere_rpc_widget
}

_sttanywhere_rpc_widget() {
  local conn=$_sttanywhere_pending_conn request=$_sttanywhere_pending_request op marker replacement anchor response cursor before after index count encoded request_id
  # Decode JSON fields as base64; never evaluate data from the peer as shell code.
  local -a decoded
  decoded=( ${(f)"$(python3 -c 'import base64,json,sys; d=json.loads(sys.stdin.readline()); print(d.get("op", "")); enc=lambda x: base64.b64encode(str(x).encode()).decode() or "-"; print(enc(d.get("marker", ""))); print(enc(d.get("replacement", ""))); a=d.get("anchor") or {}; print(enc(a.get("marker", ""))); print(enc(d.get("id", "")))' <<< "$request" 2>/dev/null)"} )
  if (( ${#decoded} != 5 )); then
    _sttanywhere_reply "$conn" '{"ok":false,"error":"invalid request"}'
    return 0
  fi
  op=$decoded[1]
  marker=$([[ $decoded[2] == - ]] || print -rn -- "$decoded[2]" | base64 -d 2>/dev/null)
  replacement=$([[ $decoded[3] == - ]] || print -rn -- "$decoded[3]" | base64 -d 2>/dev/null)
  anchor=$([[ $decoded[4] == - ]] || print -rn -- "$decoded[4]" | base64 -d 2>/dev/null)
  request_id=$([[ $decoded[5] == - ]] || print -rn -- "$decoded[5]" | base64 -d 2>/dev/null)

  if [[ $op == capture ]]; then
    # The line editor is in control of the target. Preserve the existing text and cursor.
    marker=${marker:-$_sttanywhere_marker}
    _sttanywhere_saved_marker=$marker
    _sttanywhere_saved_offset=$CURSOR
    LBUFFER+=$marker
    response=$(python3 -c 'import json,sys; print(json.dumps({"id":sys.argv[1],"ok":True,"anchor":{"marker":sys.argv[2]}},ensure_ascii=True,separators=(",",":")))' "$request_id" "$marker")
    _sttanywhere_reply "$conn" "$response"
    zle -R
    return 0
  fi

  if [[ $op == replace ]]; then
    marker=$anchor
    if [[ -z $marker || $marker != $_sttanywhere_saved_marker ]]; then
      _sttanywhere_reply "$conn" '{"ok":false,"error":"anchor mismatch"}'
      return 0
    fi
    index=$(python3 -c 'import sys; print(sys.argv[1].find(sys.argv[2])+1)' "$BUFFER" "$marker" 2>/dev/null)
    if (( index < 1 || index > ${#BUFFER} )); then
      _sttanywhere_reply "$conn" '{"ok":false,"error":"marker missing"}'
      return 0
    fi
    before=${BUFFER[1,index-1]}
    after=${BUFFER[index+${#marker},-1]}
    # Verify literal uniqueness with Python; never pattern-match transcript markers.
    local verdict
    verdict=$(python3 -c 'import sys; b,m=sys.argv[1:]; print(b.count(m))' "$BUFFER" "$marker" 2>/dev/null)
    if [[ $verdict != 1 ]]; then
      _sttanywhere_reply "$conn" '{"ok":false,"error":"marker missing or duplicated"}'
      return 0
    fi
    cursor=$CURSOR
    BUFFER="${before}${replacement}${after}"
    if (( cursor <= index - 1 )); then
      CURSOR=$cursor
    elif (( cursor >= index + ${#marker} - 1 )); then
      CURSOR=$((cursor + ${#replacement} - ${#marker}))
    else
      CURSOR=$((index - 1 + ${#replacement}))
    fi
    _sttanywhere_saved_marker=$replacement
    (( ${#replacement} )) || _sttanywhere_saved_offset=-1
    response=$(python3 -c 'import json,sys; print(json.dumps({"id":sys.argv[1],"ok":True,"anchor":{"marker":sys.argv[2]}},ensure_ascii=True,separators=(",",":")))' "$request_id" "$replacement")
    _sttanywhere_reply "$conn" "$response"
    zle -R
    return 0
  fi
  _sttanywhere_reply "$conn" '{"ok":false,"error":"unknown operation"}'
}

_sttanywhere_zle_init() {
  (( _sttanywhere_socket_fd >= 0 )) && return 0
  _sttanywhere_check_runtime || return 1
  local old_umask
  old_umask=$(umask); umask 077
  rm -f -- "$_sttanywhere_sock"
  zsocket -l "$_sttanywhere_sock" 2>/dev/null || { umask "$old_umask"; return 1; }
  _sttanywhere_socket_fd=$REPLY
  chmod 600 -- "$_sttanywhere_sock" 2>/dev/null || true
  umask "$old_umask"
  _sttanywhere_register || return 1
  zle -F $_sttanywhere_socket_fd _sttanywhere_rpc_handler
}

_sttanywhere_alt_x() {
  command "${STTANYWHERE_BIN:-sttanywhere}" toggle >/dev/null 2>&1 &!
  zle -R
}

zle -N _sttanywhere_alt_x
zle -N _sttanywhere_rpc_widget
bindkey -M emacs '^[x' _sttanywhere_alt_x
bindkey -M viins '^[x' _sttanywhere_alt_x
autoload -Uz add-zle-hook-widget add-zsh-hook
add-zle-hook-widget zle-line-init _sttanywhere_zle_init
add-zsh-hook zshexit _sttanywhere_remove_registry
