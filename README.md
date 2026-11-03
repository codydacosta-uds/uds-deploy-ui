# UDS Deploy UI

A lightweight, **read-only** browser watcher for UDS and Zarf deployments.

See **Bundle → Package → Component → Steps**, inspect full packaged YAML, and
jump from an activity card to original CLI output. Light/dark themes are included.
No frontend build, database, cloud account, cluster installation, background
service, telemetry, or Python runtime dependencies are required.

This is an independent, unofficial project—not an upstream UDS/Zarf component.

## Quick start

Requirements: **macOS or Linux**, **Python 3.10+**, `ps`, `lsof`, `zstd`, and an
existing UDS/Zarf CLI. For example, `lsof` is installed with `dnf install lsof`
on RHEL, not with Homebrew. The report catalog is audited for **UDS 0.40.0 /
Zarf 0.88.0**; other versions are best-effort, not certified.

```sh
git clone https://github.com/codydacosta-uds/uds-deploy-ui.git
cd uds-deploy-ui
./uds-watch doctor
./uds-watch setup --cli /path/to/uds
```

Setup displays the selected executable and asks for explicit approval. It does
not deploy anything. **Complete setup before starting your deployment.** Then
use your normal commands, with or without the viewer running:

```sh
uds deploy path/to/bundle.tar.zst --confirm
# Scripts, ./uds, configured absolute paths, and uds run work too.
```

Open the viewer from another terminal, even after the deployment starts:

```sh
/path/to/uds-deploy-ui/uds-watch
```

It opens a private loopback URL. Keep that terminal running; Ctrl+C stops **only
the viewer**, never the deployment. `--no-browser` prints the URL instead.
The default port is 8765, with a free-port fallback if occupied. `--port 0` always
chooses a free port; an explicitly requested fixed port is respected.

For an SSH tunnel, use the **same local and remote port** because the server
validates the Host header. Tunnel from the browser's machine and open the full
private URL printed by the remote viewer. Restarting a viewer changes its URL;
it also loses any finished captures held only by that viewer. Do not restart a
viewer holding logs you still need.

## One-time, reversible CLI registration

```sh
./uds-watch setup                         # discover PATH/current-directory CLIs
./uds-watch setup --cli /path/to/uds       # choose one native executable
./uds-watch setup --cli /path/to/uds --cli /other/path/zarf
./uds-watch setup --yes --cli /path/to/uds  # explicitly approved unattended setup
./uds-watch uninstall --cli /path/to/uds   # restore it, after commands finish
./uds-watch uninstall                     # restore all recorded registrations
```

On the first interactive viewer launch, setup is also offered once. Declining is
remembered. `--no-setup` skips this prompt; non-interactive launches never prompt
or change executables automatically. Ordinary setup does **not** edit shell
startup files, scripts, deployment tasks, or deployment configuration.

### What changes on disk?

**Yes, the selected executable entrypoint is replaced, with your approval.**
Its original native bytes and permissions are preserved beside it, for example:

```text
/path/to/uds                                  forwarding launcher
/path/to/.uds.uds-watch-native-<id>/uds        unchanged native executable
/path/to/.uds.uds-watch-native-<id>/invoke.py  output-copy helper
```

The original invocation process **execs the preserved native executable**, keeping
its PID, argv (including argv[0]), environment, cwd, stdin and native exit/signal
status. A small native forwarder copies newly allocated output channels to the
original stdout/stderr. Python receives only a bounded, best-effort copy for the
viewer: its crash, stalled logging, missing files, or a closed viewer cannot
cancel the native command or consume output still waiting to reach the terminal.
Dropped/interrupted captures are marked incomplete, never used to infer Done.

For terminal output, invocation-owned PTYs preserve `isatty`, normal interactive
input/output and window resizing. Stdin and the existing controlling terminal
are not read or replaced by capture. This is **not** identical TTY device
identity, nor certification of arbitrary full-screen tools/custom terminal
control modes. Regular redirected output keeps its separate stdout/stderr bytes.
Do not kill the native forwarding process or remove the preserved executable
while a command is running; those are the invocation's output path/executable,
not the viewer or optional Python capture worker.

Safety and scope:

- Register **each distinct executable installation** that scripts/tasks use.
  An unrelated new CLI copy is not automatically intercepted. Do not copy a
  managed launcher to create another installation; register a native CLI instead.
- Selected files must be owned, writable native ELF/Mach-O files named `uds` or
  `zarf`. Symlink selections, hard links, privileged files, and externally
  writable executables are refused. PATH discovery shows resolved real files.
  Do not use sudo to bypass these checks; use a user-owned installation.
- Existing aliases/functions are untouched. They capture only when they actually
  invoke a registered executable. Legacy shell functions can produce duplicate
  captures; remove only the watcher's managed hook when migrating.
- Uninstall refuses a running CLI. It restores the **current** preserved native
  executable, including a native self-update, without reverting user files.
  To replace an installation externally: finish commands, uninstall capture,
  update the CLI, then register it again. If an external updater overwrites the
  launcher, setup/uninstall refuses to guess; retain the preserved directory.
- Keep the clone/installed Python interpreter in place while registered. If the
  optional Python/helper package disappears, forwarding falls back to native
  execution without capture. Uninstall before relocating/removing the project.
- Registration bookkeeping is private under `$XDG_CONFIG_HOME/uds-watch` or
  `~/.config/uds-watch`. No shell config, credentials or resolved environment is
  copied into it.

### `uds run` and ambiguous output

UDS 0.40 rewrites task commands such as `./uds` to its own native executable
path. Registered `uds run` therefore also captures its **whole parent task
output**, without changing tasks. Package progress is scoped only when it can
be attributed safely. Multiple observed deployment processes, foreign/repeated
package executions, or other ambiguity disable per-CLI completion inference;
the full task output remains available with an explicit warning. Direct
registered invocations in scripts have their own separate captures.

This is not retroactive terminal recording. Setup must precede the invocation.
Temporary captures disappear at EOF; a viewer already attached retains its held
file descriptors until it closes. There is no permanent history or service.

### Distributed bootstrap executables

Registration uses small bundled, source-reviewed bootstraps: **Darwin ARM64 /
x86_64** and **Linux AArch64 / x86_64**, built against glibc 2.28 for Linux.
macOS minimum targets are 11.0 ARM64 / 10.15 Intel. Setup verifies their hashes
and executes a harmless bootstrap ABI probe **before changing a CLI**. There is
no runtime compiler, download or package installation. Unsupported ABIs refuse
registration; existing task captures can still be viewed.

The C source is `src/uds_deploy/cli_bootstrap.c`; hashes/source provenance are
in `src/uds_deploy/bootstrap/manifest.json`. These are this project's forwarding
executables, **not bundled UDS/Zarf CLI binaries**.

## Legacy/manual integration

The older shell-function installer remains explicitly available:

```sh
./uds-watch setup --legacy-shell-hook --shell bash
./uds-watch uninstall --legacy-shell-hook --shell bash
```

It changes only a managed startup block, uses private backups, validates syntax
without executing startup contents, and requires a new terminal. It does **not**
cover arbitrary scripts, `./uds`, or every `uds run` path. For nonstandard startup
files, use `--rc-file /path/to/startup --shell zsh` for both setup and uninstall.

`shell-init` prints a current-terminal-only function; `capture` is an output-only
stdin tee for explicitly wired tasks. Callers of that tee must preserve the
native pipeline status. SONIC's existing tasks already do this and do not need
executable registration. Existing aliases/custom functions are not overwritten.

SONIC and standalone share the same private per-user capture convention and
`uds_deploy/output.py`, pinned by `capture-protocol.json`. Older standalone
captures remain readable without migration. An explicit `UDS_DEPLOY_RUNTIME_DIR`
is isolated from other namespaces. Ownership, permissions, ancestry, executable
identity and held log descriptors are validated; old task tees also require
matching pipe identities. Viewers never read deployment TTYs or output pipes.

## Evidence, privacy and limits

- The server binds **127.0.0.1 only**, serves a private capability URL, and rejects
  mutation APIs. It cannot deploy, retry, cancel, signal or schedule anything.
- It reads same-user process metadata and bounded local `.tar.zst` metadata.
  OCI-only deployments without a trustworthy local artifact are not supported.
- Green **Done** may be inferred from complete, error-free sequential CLI
  advancement. In particular, terminal Helm health checks followed by CLI
  termination without reported errors can finish the final step/package/run
  when declared component coverage is complete. Inference is disclosed.
- Errors, retries, gaps, failed current-deployment checks, and ambiguous streams
  block inference. Silence/disappearance alone is not success; a late viewer
  cannot observe an authoritative native exit code.
- Full **packaged** YAML/commands are visible. No resolved external config,
  credential snapshot, decoded Helm values, or kubeconfig is saved. Optional
  read-only Kubernetes metadata checks require explicit viewer `KUBECONFIG`;
  the ambient default cluster context is not queried.
- Capture directories are 0700 and logs/status files 0600. Keep the URL,
  definitions and downloaded logs private: native output can contain secrets.
  No external assets, telemetry or database are used. Windows is unsupported.

## Optional package install

The clone launcher needs no installation. With an existing pipx installation:

```sh
pipx install .
uds-watch doctor
```

Setuptools is build-time only; the running Python code uses the standard library.
All four bootstrap artifacts and local web/font/license assets are packaged.

## Development and shared UI

The approved `uds-deploy-ui` branch of sonic-swf-iac is the UI source of truth
(`scripts/uds_deploy/web/`). Standalone `src/uds_deploy/web/` is a **verbatim
vendor copy**, not a styling fork. All 16 assets are guarded by `ui-assets.json`:

```sh
python3 scripts/sync-ui.py \
  --source /path/to/approved-checkout/scripts/uds_deploy/web \
  --manifest /path/to/approved-checkout/ui-assets.json \
  --destination src/uds_deploy/web --destination-manifest ui-assets.json --check
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_step_colors.cjs
node tests/test_log_search.cjs
node tests/test_yaml_highlighting.cjs
```

Do not independently edit or regenerate the UI/protocol pins to conceal drift.
Build native bootstraps only as a development operation with
`scripts/build-cli-bootstrap.py`; Linux ABI builds use
`tests/containers/Dockerfile.rhel8`. Build all four reviewed artifacts before
explicit `--refresh-manifest`. Runtime setup never invokes this build script.

Real, action-only SDK coverage (no application/cluster rollout):

```sh
UDS_LIVE_INTEGRATION=1 UDS_TEST_BINARY=/path/to/uds \
  python3 -m unittest discover -s tests -p test_real_cli.py -v
UDS_USER_JOURNEY=1 UDS_JOURNEY_CAPTURE_MODE=entrypoint \
  UDS_JOURNEY_LAUNCH=run UDS_TEST_BINARY=/path/to/uds \
  PLAYWRIGHT_MODULE=/path/to/node_modules/playwright \
  python3 -m unittest discover -s tests -p test_user_journey.py -v
```

Journey launch modes: `direct`, `script`, `script-relative`, `script-absolute`,
`run`, `run-absolute`. Each tests Bash/zsh, setup-before-deployment,
deployment-before-viewer, live progress and byte-exact downloads. Browser handoff
is recorded separately; normal Playwright launch does **not** certify the OS
browser integration. `UDS_JOURNEY_API_ONLY=1` explicitly selects API-only checks,
not browser evidence. `UDS_JOURNEY_CAPTURE_MODE=sonic-task` with
`UDS_SONIC_TEST_HELPER=/path/to/scripts/deploy-output.py` tests existing SONIC tees.
Never use an OS browser with a synthetic HOME or touch real Keychain settings.

## License

Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). Bundled GitLab fonts retain
their SIL OFL notices. The same unmodified light/dark UDS artwork is used by both
viewers. Artwork and trademarks remain their owners' property; no endorsement
or trademark rights are implied.
