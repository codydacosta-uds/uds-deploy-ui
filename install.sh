#!/usr/bin/env bash
# Install the shell shortcut and the existing capture tee in selected tasks.
set -euo pipefail

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) printf 'Supported platforms: macOS and Linux.\n' >&2; exit 1 ;;
esac
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  printf 'Python 3.10+ is required.\n' >&2
  exit 1
fi
root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
target="${1:-$PWD}"
if [[ -d "$target" ]]; then target="$target/tasks/swf.yaml"; fi
if [[ ! -f "$target" ]]; then
  printf 'Usage: ./install.sh /path/to/deployment-repo-or-task-file\n' >&2
  exit 1
fi
python3 "$root/scripts/task-capture.py" install "$target" --check
launcher="$HOME/.local/bin/uds-watch"
if [[ ! -x "$root/uds-watch" ]]; then
  printf 'Run install.sh from the uds-deploy-ui checkout.\n' >&2
  exit 1
fi
if [[ -e "$launcher" || -L "$launcher" ]]; then
  if [[ ! "$launcher" -ef "$root/uds-watch" ]]; then
    printf 'Refusing to replace an existing %s. Move it aside first.\n' "$launcher" >&2
    exit 1
  fi
else
  mkdir -p -- "${launcher%/*}"
  ln -s -- "$root/uds-watch" "$launcher"
fi

# Bash reads .bashrc for interactive shells and the first existing login profile.
profile="$HOME/.bash_profile"
for candidate in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
  if [[ -e "$candidate" || -L "$candidate" ]]; then profile="$candidate"; break; fi
done
begin='# >>> uds-watch shortcut >>>'
end='# <<< uds-watch shortcut <<<'
block='
# >>> uds-watch shortcut >>>
uds() {
  if [[ "${1:-}" == "watch" ]]; then
    shift
    "$HOME/.local/bin/uds-watch" "$@"
  else
    command uds "$@"
  fi
}
# <<< uds-watch shortcut <<<
'
for rc in "$HOME/.bashrc" "$profile" "${ZDOTDIR:-$HOME}/.zshrc"; do
  if [[ -f "$rc" ]] && LC_ALL=C grep -Fqx -- "$begin" "$rc"; then
    if ! LC_ALL=C grep -Fqx -- "$end" "$rc"; then
      printf 'Incomplete uds-watch shortcut block in %s; repair it before reinstalling.\n' "$rc" >&2
      exit 1
    fi
    continue
  fi
  mkdir -p -- "$(dirname -- "$rc")"
  if [[ ! -e "$rc" && ! -L "$rc" ]]; then printf '# uds-watch created this startup file\n' > "$rc"; fi
  printf '%s\n' "$block" >> "$rc"
done
python3 "$root/scripts/task-capture.py" install "$target"
printf 'Installed %s. Open a new terminal, then run: uds watch\n' "$launcher"
printf 'Official UDS is unchanged. Keep this checkout in place.\n'
