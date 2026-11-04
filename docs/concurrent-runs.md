# Optional runner integration

This is a metadata hook, not a scheduler. Keep the runner's existing commands,
flags, environment, dependency gates and exit handling. Keep the existing capture
tee **inside each invocation**, before the runner prefixes or combines output.

The runner publishes one private JSON snapshot using the installed launcher:

```python
subprocess.run(
    [str(Path.home() / '.local/bin/uds-watch'), 'publish-run'],
    input=json.dumps(snapshot).encode(),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1,
)
```

Make publication optional: if the launcher is missing, unsupported or fails,
disable publication for this run and continue deploying normally. Never put
publication success in a deployment dependency gate. No HTTP write API exists.
`install.sh` is unchanged; its launcher symlink picks up the updated code.

## Snapshot format (version 1)

Publish the complete selected plan before starting children, then update that
same snapshot after child launch, child completion and runner completion.
Serialize updates from worker threads.
Only the fields below are accepted; do not include commands, environment,
configuration, credentials or kubeconfig.

```json
{
  "schema_version": 1,
  "id": "0123456789abcdef0123456789abcdef",
  "label": "Application deployment",
  "started_at": 1793810000.0,
  "completed_at": null,
  "exit_code": null,
  "layers": [{"id": "applications", "label": "Applications"}],
  "jobs": [{
    "id": "web",
    "label": "Web",
    "layer": "applications",
    "packages": ["web"],
    "dependencies": [],
    "pid": null,
    "started_at": null,
    "completed_at": null,
    "exit_code": null
  }]
}
```

- Generate a new `uuid.uuid4().hex` ID for each run. Times are Unix seconds.
- Layers, selected jobs, package selectors and dependency job IDs come from the
  **existing runner**, not log order. The plan cannot change mid-run.
- One job represents one SDK invocation. Batch selectors belong in its
  `packages` list. Each selected package belongs to exactly one job. Map package
  dependencies to job IDs, excluding dependencies within the same batched job.
- On launch, record the runner job's start and `Popen.pid`. With the capture tee,
  this is the Bash wrapper PID; without it, it is the native CLI PID. Launch
  publication directly from the runner process that owns these children.
- After waiting, record that invocation's actual exit result and end time.
  On launch/interruption errors without an exit result, leave `exit_code` null.
  Do not manufacture zero. Terminal job results cannot be rewritten.
- Publish the runner's own result/end time after its existing scheduling finishes.
  Leave jobs that never launched untouched. Parent success requires exit zero
  **and** exit-zero results for every declared job.

The helper stamps the runner PID/start identity itself. The viewer binds children
only using same-user live process ancestry and exact package selections. It does
not group by bundle name, time proximity or similar output. Unmatched captures
remain individual deployments. A finished job with no observed capture still
shows its recorded result, but its log/detail button remains unavailable.

## Privacy and lifetime

Snapshots are bounded (256 KiB, 32 layers, 100 jobs), atomically replaced, and
stored in private `runs/*.json` files beneath the configured capture directory.
Directories are 0700; files are 0600. Symlinks, unsafe permissions, invalid graphs
and unexpected fields are rejected. No stdout, resolved configuration or secrets
are added to these records; original output remains in the existing captures.

This is session history only. A new viewer does not discover records whose owner
already exited. An attached viewer keeps observed groups and child logs in its
existing session; owner disappearance without results means **Unconfirmed**.
Old dead-owner metadata files are cleaned on later publisher startup, after a
30-second final-observation window. No database or permanent history is added.

## Isolated integration check

`tests/test_matrix_journey.py` can exercise a compatible Python runner exposing
`WatchRun`, `stream_deploy`, `schedule`, `BOOTSTRAP` and `LAYERS`. Set
`UDS_MATRIX_JOURNEY=1`, `UDS_MATRIX_RUNNER=/path/to/runner.py`,
`UDS_TEST_BINARY=/path/to/uds` and `PLAYWRIGHT_MODULE=/path/to/playwright`.
The test supplies its own dependency graph, temporary runtime and action-only
SDK packages. It tests parallel children, dependency joins, failure/not-started
states, same-page inspection and both desktop themes without deploying an
application or contacting a cluster. The normal Bash/Zsh SDK journeys separately
cover the unchanged non-grouped path and byte-exact original log downloads.
