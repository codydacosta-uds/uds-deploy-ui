#!/usr/bin/env bash
# Remove only this checkout's global launcher and managed shell blocks.
set -euo pipefail
if [[ $# -ne 0 ]]; then printf 'Usage: ./uninstall.sh (no arguments)\n' >&2; exit 2; fi
root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
python3 - "$root" <<'PY'
import os
from pathlib import Path
import sys

root=Path(sys.argv[1]);home=Path.home()
begin=b'# >>> uds-watch shortcut >>>\n'
end=b'# <<< uds-watch shortcut <<<\n'
owned=b'# uds-watch created this startup file\n'
files=[home/name for name in ('.bashrc','.bash_profile','.bash_login','.profile')]
files.append(Path(os.environ.get('ZDOTDIR') or str(home))/'.zshrc')
changes=[]
for file in files:
    if not file.is_file():continue
    data=file.read_bytes();start=data.find(begin)
    if start<0:continue
    finish=data.find(end,start)
    if finish<0 or data.count(begin)!=1 or data.count(end)!=1:
        raise SystemExit('Incomplete or duplicate shortcut block in '+str(file)+'; repair it before uninstalling.')
    left=data[:start];right=data[finish+len(end):]
    if left.endswith(b'\n'):left=left[:-1]
    if right.startswith(b'\n'):right=right[1:]
    if left and right and not left.endswith(b'\n'):left+=b'\n'
    cleaned=left+right;created=cleaned.startswith(owned)
    if created:cleaned=cleaned[len(owned):]
    changes.append((file,cleaned,created))
for file,cleaned,created in changes:
    if created and not cleaned and not file.is_symlink():file.unlink()
    else:file.write_bytes(cleaned)
launcher=home/'.local/bin/uds-watch'
if launcher.is_symlink() and launcher.resolve()==root/'uds-watch':launcher.unlink()
print('Removed the uds-watch shortcut. Open a new terminal to reload your shell.')
print('Official UDS, deployment tasks, and unrelated settings were left unchanged.')
PY
