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

## Optional global setup

```bash
./install.sh
# Open a new terminal, then use the same watcher from any directory:
uds watch
uds watch --port 0
```

No repository path is needed. The installer links `~/.local/bin/uds-watch` to
this checkout and configures Bash/Zsh. Keep the checkout in place.

The shell function opens the viewer for `uds watch` and copies output from
plain `uds deploy ...` (or `uds d ...`) through the existing capture helper.
Arguments and the native exit status are preserved. Other commands pass straight
through to the official CLI. Put deployment flags after `deploy` to use capture.

Reinstalling updates the managed shell block without duplicating it. The
installer never replaces the official UDS binary or edits deployment task files.

To remove this global setup:

```bash
./uninstall.sh
```

Open a new terminal afterward. Uninstallation leaves the official UDS binary,
existing task capture hooks, unrelated shell settings, and this checkout intact.

## Deploy normally

After installation, run `uds deploy ...` in another Bash/Zsh terminal.
The shell function copies the native CLI's output; the viewer only reads it.

Start the viewer before deployment or while it is still running. It never reads
terminal history or attaches to a deployment's TTY.

`./uds`, absolute executable paths, `command uds`, `uds run`, and commands inside
scripts bypass this shell capture. Those workflows, including SONIC tasks, need
an explicit capture tee configured separately. The existing pattern remains:

```bash
./uds deploy ... 2>&1 | ("$HOME/.local/bin/uds-watch" capture || cat)
exit "${PIPESTATUS[0]}"  # Bash task owns the native status
```

Without shell capture or an explicit task tee, only partial diagnostic logs may
be available. Arbitrary commands and scripts are not automatically recorded.

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
- Component rows show the current/last operation, status and elapsed time; click
  a row for individual steps. Package/component/operation timing uses SDK log
  clocks, not watcher attachment time. `~` marks estimated spans; `—` means timing
  is unavailable. No historical averages are stored.
- Concurrent packages stay in separate scoped activity cards. Missing or
  concurrent execution evidence never creates dependency arrows or inferred
  success.
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
old version's uninstall command too. Those binary-registration installers are
not included here. The current installer only configures the Bash/Zsh function
and existing stdin tee; it never replaces a CLI executable.

## Development

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
node tests/test_step_colors.cjs
node tests/test_activity.cjs
node tests/test_discovery.cjs
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
