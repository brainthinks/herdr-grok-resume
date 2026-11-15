#!/bin/bash
# Install or remove the Grok resume hook for the Herdr desktop app.
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
begin='# >>> herdr grok resume >>>'
end='# <<< herdr grok resume <<<'
bashrc=${HOME}/.bashrc
dest=${HOME}/.config/herdr-app/grok-resume
hook=${HOME}/.grok/hooks/herdr-resume.json

remove_block() {
  [[ -f $bashrc ]] || return 0
  python3 - "$bashrc" "$begin" "$end" << 'PY'
import pathlib, sys
path, begin, end = sys.argv[1:]
file = pathlib.Path(path)
text = file.read_text()
start = text.find(begin)
stop = text.find(end)
if start == -1 or stop == -1 or stop < start:
    sys.exit(0)
stop = stop + len(end)
if stop < len(text) and text[stop] == "\n":
    stop += 1
if start > 0 and text[start - 1] == "\n":
    start -= 1
file.write_text(text[:start] + text[stop:])
PY
}

uninstall() {
  remove_block
  rm -f "$hook"
  rm -f "$dest/resume.py"
  rmdir "$dest" 2>/dev/null || true
  echo "removed herdr grok resume"
}

install() {
  command -v python3 >/dev/null
  command -v hc >/dev/null || echo "warning: hc is not on PATH yet; install herdr-core before using a pane" >&2
  mkdir -p "$dest" "$(dirname "$hook")"
  cp "$root/resume.py" "$dest/resume.py"
  chmod +x "$dest/resume.py"
  cp "$root/hooks/herdr-resume.json" "$hook"
  snippet=$(cat "$root/bashrc.snippet")
  if [[ -f $bashrc ]] && grep -qF "$begin" "$bashrc"; then
    python3 - "$bashrc" "$begin" "$end" "$snippet" << 'PY'
import pathlib, sys
path, begin, end, snippet = sys.argv[1:]
file = pathlib.Path(path)
text = file.read_text()
start = text.find(begin)
stop = text.find(end)
if start == -1 or stop == -1 or stop < start:
    raise SystemExit("bashrc markers are incomplete")
stop = stop + len(end)
if stop < len(text) and text[stop] == "\n":
    stop += 1
file.write_text(text[:start] + snippet + "\n" + text[stop:])
PY
  else
    touch "$bashrc"
    printf '\n%s\n' "$snippet" >> "$bashrc"
  fi
  echo "installed herdr grok resume"
  echo "  $dest/resume.py"
  echo "  $hook"
  echo "  marked block in $bashrc"
  echo "start Grok in a Herdr pane. trust the folder if Grok asks."
}

case ${1:-} in
  --uninstall) uninstall ;;
  "") install ;;
  *) echo "usage: ./install.sh [--uninstall]" >&2; exit 2 ;;
esac
