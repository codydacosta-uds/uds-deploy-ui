# UDS Deploy UI

A lightweight, **read-only** browser watcher for UDS and Zarf deployments.

See **Bundle → Package → Component → Steps**, inspect full packaged YAML with
syntax highlighting, and jump from an activity card to its original CLI output.
Light and dark themes are included. No frontend build, database, cloud account,
cluster installation, or Python runtime dependencies are required.

This is an independent, unofficial project—not an upstream UDS/Zarf component.

## Quick start

Requirements: **macOS or Linux**, **Python 3.10+**, `ps`, `lsof`, `zstd`, and the
UDS or Zarf CLI already on your PATH. The report catalog is source-audited for
**UDS 0.40.0 / Zarf 0.88.0**; other versions are best-effort, not certified.

```sh
git clone --branch v0.1.0-preview.4 https://github.com/codydacosta-uds/uds-deploy-ui.git
cd uds-deploy-ui
./uds-watch doctor
./uds-watch
```

This initial public preview is pinned to a version tag; cloning it checks out
that tested version in detached-HEAD mode. The repository's default branch is
not initialized or changed by this preview.

The last command opens your browser. Leave that terminal running; Ctrl+C stops
**only the viewer**, never your deployment. Use `--no-browser` to print its
private loopback URL instead. By default the viewer tries port 8765 and
**automatically chooses a free loopback port if it is occupied**, without stopping
the existing listener. `--port 0` always chooses a free port; an explicitly
requested fixed `--port` is honored and errors if unavailable.

### Automatic capture: approve setup once, then deploy normally

On its **first interactive launch**, `./uds-watch` asks whether to enable automatic
capture. Answer **y** to add a small, clearly marked startup block. Nothing is
edited without your approval. Declining is remembered; use `./uds-watch setup`
if you change your mind. Use `./uds-watch --no-setup` to skip the prompt.
Non-interactive viewer launches never prompt or edit startup files.

After approving, **open a new deployment terminal**. Existing terminals cannot
be changed by a child process. Leave the viewer running and deploy as usual:

```sh
uds deploy path/to/bundle.tar.zst --confirm
# Or, when using standalone Zarf:
zarf package deploy path/to/package.tar.zst --confirm
```

You can also configure capture explicitly:

```sh
./uds-watch setup                 # shows files and asks for approval
./uds-watch setup --yes           # explicitly approved unattended setup
./uds-watch setup --shell bash    # choose a shell explicitly
./uds-watch uninstall             # remove only the managed startup block
```

For zsh, setup uses `$ZDOTDIR/.zshrc` or `~/.zshrc`. For Bash, it configures
`~/.bashrc` and the existing login startup file (or creates `~/.bash_profile` if
none exists). This supports both login and non-login terminals. A shared
`.profile` block is guarded for the selected shell. For nonstandard dotfiles,
use `setup --rc-file /actual/startup/file --shell zsh`; select the same file when
uninstalling. Symlinked, hard-linked, read-only, or invalid-syntax startup files
are refused rather than silently replaced.

### Does this change or replace UDS?

**No UDS/Zarf binary or deployment configuration is edited.** With your consent,
setup adds optional shell functions named `uds` and `zarf`. They call the actual
native binaries with unchanged arguments and copy output to your terminal and
a private temporary capture. Unrelated commands pass through; unknown global
flag arity is not guessed. The native CLI's exit status is returned, and Ctrl+C
is handled by the CLI while the capture helper drains its cleanup output.

Safety measures:

- Existing aliases and custom functions are **not overwritten**. A conflicting
  wrapper stays in control and capture is skipped until you resolve it explicitly.
- Existing startup bytes are retained outside the managed block. Syntax is
  checked without executing your configuration. Edits are atomic, repeatable,
  and reversible; detected concurrent edits are refused.
- Backups are kept under `~/.config/uds-watch/backups` (or `$XDG_CONFIG_HOME`),
  with directory mode 0700 and file mode 0600. **They may contain sensitive existing
  shell settings**; they stay local and are never served, uploaded, or printed.
- Uninstall removes only the managed block and preserves later user edits. It
  does not blindly restore a backup over your changes. Open a new terminal
  afterward; existing terminal functions remain unchanged.
- If the clone is moved/deleted or the native CLI is absent, the startup block
  safely skips loading the hook. It does not prevent your shell from opening.
- Capture combines stdout/stderr. Piping can change animated progress rendering;
  interactive input remains in your deployment terminal. This is not a promise
  of compatibility with every custom wrapper or future CLI version.

**Manual, current-terminal-only option:** if you do not want startup files edited,
use `eval "$(/path/to/uds-deploy-ui/uds-watch shell-init)"`. Add `--tool zarf` for
standalone Zarf. This command only prints shell code and never edits files.
If you enabled the watcher function in that terminal, `unset -f uds` disables
it; do not unset your own unrelated custom functions.

For scripts or existing deployment tasks, an output-only stdin tee is available
as `uds-watch capture`. The caller must preserve the native CLI's pipeline exit
status; the interactive shell hook handles that automatically.

## What the watcher does—and does not do

- Observes same-user UDS/Zarf process metadata and supported local `.tar.zst`
  artifacts. It never reads terminal devices, scrollback, or another process's pipe.
- Reads bounded artifact metadata, not a second extracted image payload.
- Serves a capability-protected URL on **127.0.0.1 only**. All mutation APIs are
  denied; there is no deployment engine, cancellation, retry API, or scheduler.
- Shows explicit CLI reports plus green **Done** inferred when the same sequential
  CLI advances without a reported error. Inferred completion is disclosed in details.
- Does **not** treat process disappearance, image transfer percentage, or silence
  as authoritative success. A non-child process's exit code is unknown.
- Shows full **packaged** config values and commands. External `uds-config.yaml`,
  CLI overrides, resolved credentials, live Helm values, and kubeconfig contents
  are not copied into the viewer.
- Optionally reads independent Kubernetes readiness/revision metadata **only**
  when `KUBECONFIG` is explicitly set in the viewer's environment. The ambient
  default cluster context is never queried.
- Keeps current-session state in memory. Temporary capture files are private
  (directories 0700; files 0600) and removed when their capture ends. An attached
  viewer can retain its open descriptor until it stops. Download logs first if
  you need to retain them.

Keep the viewer URL, packaged definitions, and original logs private: packaged
values or CLI output can contain sensitive information. There is no telemetry,
external font request, or external JavaScript request.

Remote OCI-only deployments without an authoritative local artifact are not yet
supported. Windows is not supported. There is no promise of complete lifecycle
reporting from every stock CLI version.

## Optional package install

The clone launcher above needs no installation. If you already use pipx, you can
install this checkout for an `uds-watch` command available from any directory:

```sh
pipx install .
uds-watch doctor
```

This uses setuptools only to build/install the package; the running application
uses Python's standard library.

## One shared UI—no styling forks

The approved `uds-deploy-ui` branch of sonic-swf-iac is the UI source of truth
(`scripts/uds_deploy/web/`). Standalone `src/uds_deploy/web/` is a **verbatim vendor
copy**, not a second design: HTML, JavaScript, CSS, fonts, logos, and the development
reload script stay byte-for-byte identical. Only backend integration/packaging
differs. The shared HTML defaults to the approved read-only watcher mode.

A pinned `ui-assets.json` and `tests/test_ui_parity.py` reject local drift.
Maintainers synchronize from the approved checkout:

```sh
python3 scripts/sync-ui.py \
  --source /path/to/approved-checkout/scripts/uds_deploy/web \
  --manifest /path/to/approved-checkout/ui-assets.json \
  --destination src/uds_deploy/web --destination-manifest ui-assets.json
```

Repeat the command with `--check` to verify parity. Do not independently edit the
standalone copy or merely regenerate its manifest. Run parity checks in both
repositories and Playwright on affected views. This is development-time syncing;
standalone users do not need the original repository to install or run the tool.

## Development

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_step_colors.cjs
node tests/test_log_search.cjs
node tests/test_yaml_highlighting.cjs
```

For real, action-only SDK coverage (no cluster or application rollout):

```sh
UDS_LIVE_INTEGRATION=1 UDS_TEST_BINARY=/path/to/uds \
  python3 -m unittest discover -s tests -p test_real_cli.py -v
```

To test the full deployment-first journey with real stock UDS and the real
standalone viewer API:

```sh
UDS_USER_JOURNEY=1 UDS_TEST_BINARY=/path/to/uds \
  PLAYWRIGHT_MODULE=/path/to/node_modules/playwright \
  python3 -m unittest discover -s tests -p test_user_journey.py -v
```

This enables the hook in an isolated fake home, starts an action-only deployment
**before** the watcher, then verifies live progress, completion, and byte-exact
log downloads in both Bash and zsh. Browser handoff is recorded without opening
an OS browser; the page is opened with normal Playwright launch and its default
safety flags. It does not verify your OS's default-browser integration or touch
its settings. No real cluster/application rollout is involved.

To visually check a genuinely empty viewer (with no running deployment):

```sh
PLAYWRIGHT_MODULE=/path/to/node_modules/playwright node tests/test_empty_viewer_browser.cjs
```

This starts the real read-only server, verifies both UDS logo variants, empty-state
contrast and responsive layout, and cleans up its own viewer/browser afterward.

For Playwright against an existing private local capture, set
`UDS_WATCHER_SOURCE_URL`, `UDS_WATCHER_CAPTURE_ID`, and `PLAYWRIGHT_MODULE`, then
run `node tests/test_real_capture_browser.cjs`. It starts and cleans up a temporary
GET-only test server; no captured lifecycle state is injected or saved.

Node/Playwright are development-only tools, not runtime requirements. Browser
checks must use actual captured deployments; isolated edge-case fixtures must
be identified as such. Do not redeploy real applications just to inspect styling.

## License

Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE) for source attribution and
standalone modifications. Bundled GitLab fonts retain their SIL OFL notices.
The header uses the same unmodified light/dark UDS artwork as the integrated
viewer. Product artwork and trademarks remain their owners' property; the
project's code license does not grant trademark rights or imply endorsement.
