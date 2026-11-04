# UDS Deploy UI

A lightweight, **read-only** browser viewer for UDS/Zarf deployments. See packages,
components, steps, original logs and packaged YAML while you deploy normally.

**Your terminal runs the deployment. This tool only watches it.** It cannot start,
retry, cancel or schedule deployments. No database, service installation, build
step, or Python/JavaScript dependency installation is required.

## Quick start

You need **macOS or Linux**, **Bash or Zsh**, **Python 3.10+ available as `python3`**,
Git, `ps`, `lsof`, `zstd`, and your normal **UDS executable on `PATH`**.

### 1. Clone, check prerequisites and install the shell shortcut

```bash
git clone https://github.com/codydacosta-uds/uds-deploy-ui.git
cd uds-deploy-ui
./uds-watch doctor
./install.sh
```

If `doctor` reports a missing prerequisite, fix it before continuing. For example,
on RHEL a missing `lsof` can be installed with `sudo dnf install lsof`.

The installer adds a small Bash/Zsh function and links `~/.local/bin/uds-watch`
to this checkout. It **does not replace UDS or edit your deployment repository**.
Keep this checkout in place, and **open new terminals** so the function is loaded.

### 2. In a new terminal, open the viewer

```bash
uds watch
```

Your browser opens on **Current tasks**. Keep the viewer terminal running.

### 3. In another new terminal, run your usual deployment

```bash
cd /path/to/your/deployment-project
uds deploy /path/to/your/uds-bundle.tar.zst --confirm
```

Replace the example paths with your project and built bundle. Keep your usual
credentials, configuration, environment variables and deployment flags. Put flags
**after `deploy`**. The installed function captures output automatically and
preserves the native command's arguments and exit status.

In **Current tasks**, click the deployment name, status badge or **View** to open
its details. Updates arrive automatically; you do not need to refresh the page.
Use **← Current tasks** to return to the overview.

**Already deploying?** You can attach while the command is still running if
capture was enabled when it started. Output produced without capture cannot be
recovered from terminal history.

## Which commands are captured?

| How you deploy | Capture |
| --- | --- |
| `uds deploy ...` or `uds d ...` in a new Bash/Zsh terminal after installation | Automatic |
| `./uds deploy ...`, an absolute executable path, or `command uds ...` | Add an explicit tee, below |
| `uds run ...`, a script, or a Python/concurrent runner | Add the tee around the actual deployment command inside the task or runner |
| `zarf package deploy ...` or `uds zarf package deploy ...` | Add an explicit tee |

The installer only intercepts plain `uds deploy` / `uds d`; it does not rewrite
scripts or automatically capture commands launched by another program.

### Using `./uds` or your own Bash task

After installing, wrap the deployment command like this. The subshell keeps
`exit` from closing an interactive terminal and preserves the deployment status:

```bash
(
  ./uds deploy /path/to/your/uds-bundle.tar.zst --confirm 2>&1 | ("$HOME/.local/bin/uds-watch" capture || cat)
  exit "${PIPESTATUS[0]}"
)
```

Use **Bash** for this example, including when configuring a task's shell. Replace
only the deployment command with your normal command and flags. The existing
capture helper reads stdin; it never launches or takes ownership of UDS.

Do not add a second tee to plain `uds deploy` when shell capture is already
installed. For concurrent runners, capture each native invocation separately—not
the mixed output of the whole runner. An integrated runner can also publish a
small optional run record to group its invocations into one matrix. Without that
record, individual invocations remain separate deployments.

Without capture, the viewer may find only partial diagnostic output and cannot
reliably show every step.

### Grouped concurrent runs

An integrated runner appears as **one Current tasks entry** with expandable layer
cards, parallel jobs and declared dependency connections. Select a captured job
to open its existing components and logs **below the matrix, on the same page**.
Each job shows its status, start time and elapsed time.

Normal `uds deploy` keeps the existing view. Grouping is explicit: using the same
bundle never groups unrelated deployments. Job results come from the runner's
actual exit results; missing results remain unconfirmed. Jobs not launched after
a failure are marked **Not started**, not successful.

**No installer change or new deployment command is needed.** The runner needs a
one-time integration; installing the viewer alone does not expose arbitrary
scripts' dependency graphs. Update the viewer and integrated runner before the
next run. Already-running deployments are not retroactively grouped.
See [runner integration](docs/concurrent-runs.md).

## Using the viewer

- Click a component for its individual steps and packaged resources.
- **Jump to activity** opens the exact captured log line for that activity, when
  available. **View all logs** opens the general deployment output.
- Package config buttons and **Bundle YAML** show the full **packaged** YAML,
  not resolved external configuration or live Helm values.
- `~` before a duration means approximate; `—` means reliable timing is unavailable.
  Hover over a duration or status for its evidence.
- Done may be inferred from complete, error-free sequential deployment output
  and completed observed work. Silence or a disappearing process alone is never
  success. Uncertain results remain unconfirmed/unknown.

## Logs, privacy and session history

Completed runs remain available **while the viewer process stays running**.
Refreshing or closing the browser does not clear that session. Stopping or
restarting the viewer loses its retained history and changes its private URL.
**Download any logs you need before stopping it.** There is no permanent history
or database.

The server listens only on localhost. Treat its private URL, logs and packaged
YAML as sensitive. The viewer never reads deployment TTYs or terminal history.
Ctrl+C in the **viewer** terminal stops only the viewer—not your deployment.
Optional cluster checks require an explicitly set `KUBECONFIG`; the viewer does
not use a default cluster context.

## Troubleshooting

- **`uds watch` is not recognized:** open a new Bash/Zsh terminal after installing.
  Run `type uds`; it should report a shell function. Ensure the official UDS
  executable is still on `PATH`.
- **No deployment or missing steps:** check the capture table above. The viewer
  must run on the **same machine and as the same user** as the deployment. Capture
  must have been enabled before the output you want to see was produced.
- **Browser did not open:** run `uds watch --no-browser` and open the full private
  URL printed in the terminal.
- **Port conflict:** the default port is 8765, with automatic free-port fallback.
  Use `uds watch --port 0` for a free port, or `--port NUMBER` for a fixed one.
- **Remote host:** run the viewer on the deployment host, forward the same local
  and remote port over SSH, and open the full private URL it prints.

The report catalog is audited for UDS 0.40.0 / Zarf 0.88.0; other versions are
best-effort. Windows and OCI-only deployments without local artifacts are not
supported. Zarf-only workflows use an explicit capture tee rather than the UDS
shell shortcut.

## Updating, viewer-only use and uninstalling

Update this checkout normally. Re-run `./install.sh` if its shell setup changes;
reinstallation is idempotent. Backend updates load in a new viewer session—save
any held logs before stopping an existing one.

To run without installing shell shortcuts, use `./uds-watch` from the checkout.
This opens the viewer but **does not enable automatic capture**. It can observe
already-configured captures or partial diagnostic output.

To remove the shell setup:

```bash
# From this checkout:
./uninstall.sh
```

Open a new terminal afterward. Uninstallation removes only the managed function
and launcher link. It preserves UDS, your deployment tasks, unrelated shell
settings and this checkout. Remove separately configured task tees yourself if
no longer wanted.

If you used executable registration in version 0.1.0a6, use **that version's**
`./uds-watch uninstall` before updating, while commands are idle. That obsolete
registration mechanism is not included here.

## Development

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
node tests/test_step_colors.cjs
node tests/test_activity.cjs
node tests/test_discovery.cjs
node tests/test_matrix.cjs
node tests/test_log_search.cjs
node tests/test_yaml_highlighting.cjs
```

Shared UI assets are pinned by `ui-assets.json`; use `scripts/sync-ui.py` to keep
reviewed changes identical across distributions. Capture producers/readers share
`uds_deploy/output.py`, pinned by `capture-protocol.json`. Captures use
`uds-watch-output-<uid>` in the system temporary directory, or
`UDS_DEPLOY_RUNTIME_DIR/output` when explicitly configured. Other capture
namespaces are not read.

Isolated action-only SDK tests use `UDS_LIVE_INTEGRATION=1` or
`UDS_USER_JOURNEY=1` with `UDS_TEST_BINARY=/path/to/uds`. Browser journeys also
need `PLAYWRIGHT_MODULE=/path/to/node_modules/playwright`. They never deploy a
real application or use an OS browser with a fake HOME. The optional matrix SDK
journey uses `UDS_MATRIX_JOURNEY=1` and `UDS_MATRIX_RUNNER=/path/to/integrated-runner.py`;
see the integration document for its fixture requirements.

## License

Independent, unofficial project. Apache-2.0; see [LICENSE](LICENSE) and
[NOTICE](NOTICE). Bundled fonts retain their OFL notices. UDS artwork and product
trademarks remain their owners' property; no affiliation is implied.
