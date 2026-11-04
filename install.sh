#!/usr/bin/env bash
# Explicit shell setup only. Never replace UDS or edit deployment repositories.
set -euo pipefail
if [[ $# -ne 0 ]]; then printf 'Usage: ./install.sh (no arguments)\n' >&2; exit 2; fi
root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
python3 - "$root" <<'PY'
from pathlib import Path
import os
import sys

if sys.version_info<(3,10):raise SystemExit('Python 3.10+ is required.')
if sys.platform not in ('darwin','linux'):raise SystemExit('Supported platforms: macOS and Linux.')
root=Path(sys.argv[1]);home=Path.home();source=root/'uds-watch';launcher=home/'.local/bin/uds-watch'
if not os.access(source,os.X_OK):raise SystemExit('Run install.sh from the uds-deploy-ui checkout.')
if (launcher.exists() or launcher.is_symlink()) and (not launcher.is_symlink() or launcher.resolve()!=source):
    raise SystemExit('Refusing to replace an existing '+str(launcher)+'. Move it aside first.')
block=b'''# >>> uds-watch shortcut >>>
uds() {
  if [[ "${1:-}" == "watch" ]]; then
    shift
    "$HOME/.local/bin/uds-watch" "$@"
  elif [[ "${1:-}" == "deploy" || "${1:-}" == "d" ]]; then
    # Preserve the native exit status in Bash and Zsh respectively.
    (exec /usr/bin/env uds "$@") 2>&1 | ("$HOME/.local/bin/uds-watch" capture || cat)
    return "${PIPESTATUS[0]:-${pipestatus[1]}}"
  else
    command uds "$@"
  fi
}
# <<< uds-watch shortcut <<<'''
begin=b'# >>> uds-watch shortcut >>>';end=b'# <<< uds-watch shortcut <<<'
profiles=[home/name for name in ('.bash_profile','.bash_login','.profile')]
profile=next((path for path in profiles if path.exists() or path.is_symlink()),profiles[0])
files=[home/'.bashrc',profile,Path(os.environ.get('ZDOTDIR') or str(home))/'.zshrc'];changes=[]
for file in files:
    exists=file.exists() or file.is_symlink();data=file.read_bytes() if exists else b'# uds-watch created this startup file\n'
    if begin in data or end in data:
        start=data.find(begin);finish=data.find(end)
        if start<0 or finish<start or data.count(begin)!=1 or data.count(end)!=1:
            raise SystemExit('Incomplete or duplicate shortcut block in '+str(file)+'; repair it before reinstalling.')
        updated=data[:start]+block+data[finish+len(end):]
    else:updated=data+b'\n'+block+b'\n\n'
    if updated!=data:changes.append((file,updated))
launcher.parent.mkdir(parents=True,exist_ok=True)
if not launcher.is_symlink():launcher.symlink_to(source)
for file,data in changes:
    file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
print('Installed uds watch and capture for plain uds deploy. Open a new terminal to use them.')
print('Official UDS and deployment task files are unchanged. Keep this checkout in place.')
PY
