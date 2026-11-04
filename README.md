# UDS Deploy UI

A small, **read-only** browser viewer for UDS/Zarf deployment output.

It shows packages, components, steps, original logs and packaged YAML.
It does not deploy, retry, cancel or schedule anything.

## Run it

Requires macOS or Linux, Python 3.10+, `ps`, `lsof`, `zstd`, and UDS or Zarf.
On RHEL, install a missing `lsof` with `sudo dnf install lsof`.

```bash
git clone https://github.com/codydacosta-uds/uds-deploy-ui.git
cd uds-deploy-ui
./uds-watch doctor
./uds-watch
```

The last command opens the browser. Keep its terminal running.
Use `./uds-watch --no-browser` to print the private URL instead.

Running the viewer never installs anything or changes your shell or UDS binary.
Terminal colors are automatic; set `NO_COLOR=1` to disable them.

## Optional global shortcut

```bash
./install.sh /path/to/deployment-repo
# Open a new terminal, then use the same watcher from any directory:
uds watch
uds watch --port 0
```

The installer links `~/.local/bin/uds-watch` to this checkout and adds the
`uds watch` shortcut to Bash/Zsh startup files. Keep the checkout in place.
Re-running installation does not duplicate configuration. Other `uds` commands
pass through to the official CLI with their arguments and exit status unchanged.
The installer also connects deployment output to the existing capture helper in
`tasks/swf.yaml` inside the selected repository. You can pass a task-file path
instead. It handles `uds deploy`, `./uds deploy`, and package deploy actions;
existing capture hooks are left alone. No binary is replaced, and commands
outside the configured tasks are not automatically captured.

Only straightforward Bash task actions are supported. Unsupported layouts fail
without guessing or rewriting unrelated commands.

To remove only this installation's shortcut and shell configuration:

```bash
./uninstall.sh /path/to/deployment-repo
```

Open a new terminal afterward. Uninstallation removes its marked task capture
wiring and shell shortcut, leaving the official UDS binary, pre-existing capture
hooks, unrelated shell settings, and this checkout intact.

## Deploy normally

Run your normal **capture-enabled SONIC deployment task** in another terminal.
The task copies the native CLI's output; this app only reads that capture.

The viewer can start before the task or afterward, while deployment is still
running. It never reads terminal history or attaches to a deployment's TTY.

Full progress requires that task-side output capture. A plain `uds deploy`
outside a capture-enabled task may expose only partial diagnostic logs.
This viewer does not automatically record arbitrary commands or scripts.

## Things to know

- Ctrl+C in the viewer terminal stops **only the viewer**. Your deployment stays
  under the original CLI and deployment terminal.
- The browser URL and logs are private. The server binds only to localhost.
- The default port is 8765, with a free-port fallback if occupied. Use `--port 0`
  for a free port or `--port NUMBER` to request a fixed one.
- For SSH forwarding, use the same local and remote port and open the full
  private URL printed by the remote viewer.
- Captures are temporary. An attached viewer holds finished logs until it
  closes; download them first if you want to keep them. Restarting the viewer
  changes its URL and loses those held captures.
- Unknown or missing evidence stays unknown. Green completion can be inferred
  from complete, error-free sequential CLI progress, including final Helm health
  checks; the UI explains that inference. Disappearance or silence alone is not
  success.
- Definitions are the **packaged** YAML, not resolved credentials or live Helm
  values. Optional cluster metadata checks require explicit `KUBECONFIG` in the
  viewer environment. No default cluster context is queried.

The report catalog is audited for UDS 0.40.0 / Zarf 0.88.0. Other versions are
best-effort. Windows and OCI-only deployments without local artifacts are not
supported. No database, telemetry, external assets or permanent history is used.

## Removing the previous automatic setup

If you enabled CLI registration in 0.1.0a6, run **that version's**
`./uds-watch uninstall` before updating, while CLI commands are idle. It restores
the preserved native executable. Remove any older managed shell hook with its
old version's uninstall command too. Those binary-registration/automatic-capture
installers are not included here; `install.sh` adds the shell shortcut and an
explicit task-side capture tee, never a binary wrapper.

## Development

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
node tests/test_step_colors.cjs
node tests/test_log_search.cjs
node tests/test_yaml_highlighting.cjs
```

The UI is a verbatim copy of the approved SONIC `uds-deploy-ui` branch, guarded
by `ui-assets.json`. Do not independently restyle it. Capture producers/readers
share `uds_deploy/output.py`, pinned by `capture-protocol.json`.

Isolated action-only SDK tests use `UDS_LIVE_INTEGRATION=1` or
`UDS_USER_JOURNEY=1` with `UDS_TEST_BINARY=/path/to/uds`. Browser journeys also
need `PLAYWRIGHT_MODULE=/path/to/node_modules/playwright`. They never deploy a
real application or use an OS browser with a fake HOME.

## License

Independent, unofficial project. Apache-2.0; see [LICENSE](LICENSE) and
[NOTICE](NOTICE). Bundled fonts retain their OFL notices. UDS artwork and product
trademarks remain their owners' property; no affiliation is implied.
