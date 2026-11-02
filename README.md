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
git clone --branch v0.1.0-preview.1 https://github.com/codydacosta-uds/uds-deploy-ui.git
cd uds-deploy-ui
./uds-watch doctor
./uds-watch
```

This initial public preview is pinned to a version tag; cloning it checks out
that tested version in detached-HEAD mode. The repository's default branch is
not initialized or changed by this preview.

The last command opens your browser. Leave that terminal running; Ctrl+C stops
**only the viewer**, never your deployment. Use `--no-browser` to print its
private loopback URL instead. If the port is occupied, reuse your existing
viewer URL or run `./uds-watch --port 0` for an available port.

### Enable automatic capture in your deployment terminal

In the terminal where you deploy, run this once, using the actual clone path:

```sh
eval "$(/path/to/uds-deploy-ui/uds-watch shell-init)"
```

Then deploy **as usual**, from your normal working directory:

```sh
uds deploy path/to/bundle.tar.zst --confirm
```

The opt-in shell function calls the native UDS binary with your unchanged
arguments and copies its output to your terminal and a private temporary file.
It does not start the viewer, select packages, schedule, retry, or stop work.
The native CLI's exit status is returned. Ctrl+C goes to the CLI; the capture
helper drains its final cleanup output.

- Bash and zsh are supported. Override detection with `shell-init --shell bash`
  or `shell-init --shell zsh`.
- For standalone Zarf, enable `shell-init --tool zarf`, then use
  `zarf package deploy ...` normally.
- Only recognized deployment commands are captured; unrelated commands pass
  through. Unknown global flag arity is not guessed.
- Existing `uds` aliases/functions are **not overwritten**. Resolve that conflict
  explicitly before enabling the hook.
- Disable the hook with `unset -f uds` (or `unset -f zarf`). Your binary is unchanged.
- Nothing edits your shell startup files. To enable it in future terminals, you
  may add the same `eval` line to your own `.zshrc` or `.bashrc`.
- Capture combines stdout/stderr. Piped output can change the CLI's animated
  progress rendering; interactive input remains in your deployment terminal.

For scripts or existing deployment tasks, an output-only stdin tee is also
available as `uds-watch capture`. The caller must preserve the native CLI's
pipeline exit status; the shell hook handles that for interactive use.

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
Official product logos are not distributed. Product names do not imply endorsement.
