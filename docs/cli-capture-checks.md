# CLI capture verification

Registration is tested only against isolated native fixture copies and stock
UDS 0.40.0 action-only packages/bundles. No application or cluster deployment,
installed CLI registration, production installation, or viewer restart is part
of this verification.

## Native preservation

`tests/test_entrypoints.py`, `test_registration_safety.py` and
`test_terminal_registration.py` cover:

- Original argv/argv[0], environment, cwd, stdin, stdout/stderr bytes and status.
- Original invocation PID execs the preserved native executable.
- Native Ctrl+C cleanup, targeted SIGTERM/SIGKILL status, Bash/zsh foreground
  stop/resume, test-owned prompt input, terminal flags and initial dimensions.
- Capture-worker crash while idle **and while output is backpressured**.
  The latter previously lost bytes; the independent native forwarder fixes it.
- A paused capture worker cannot block native output; bounded copy failure is
  explicitly marked incomplete. Only an explicit EOF frame certifies capture.
- Rollback after partial preparation or bookkeeping failure; repeat setup;
  self-update preservation; refusal to relocate a running CLI; symlink/hardlink
  and edited-launcher refusal; preservation of unrelated files.
- Hash/source provenance and a harmless executable ABI probe before setup.

Terminal cases use only newly allocated fixture PTYs. They are not certification
of arbitrary full-screen tools, custom terminal modes, or identical TTY devices.

## Real SDK launch paths

All six modes in `tests/test_user_journey.py` are exercised in Bash and zsh:

1. Direct PATH call.
2. Script using PATH.
3. Script using `./uds`.
4. Script using an absolute registered path.
5. `uds run` with `./uds` (UDS's native self-path rewriting).
6. `uds run` with an absolute registered path.

Each performs setup first, starts the deployment next, and opens the real viewer
last. It checks late attachment, live component/action transitions, native
success, intact capture EOF, and original log downloads. Parent-task fallback
is compared with the actual outer terminal file, not merely another read of the
same capture. Direct captures preserve independent stdout/stderr in the native
conformance tests.

The matrix passes locally on macOS ARM64 and Rocky Linux 8 ARM64/x86_64. The
local x86_64 Linux container uses CPU translation, not a native x86_64 host;
CI additionally exercises native Linux x86_64 and macOS Intel/ARM runners.
Linux SDK binaries are temporary upstream-checksummed fixtures, not distributed
artifacts. Linux SDK journeys are explicitly API-only. macOS journeys use
normal Playwright launch with the existing browser cache, real captures,
light/dark screenshots at desktop/mobile widths and actual byte downloads.
Browser handoff is recorded separately: no OS browser/Keychain integration is
claimed.

Existing SONIC output tees are checked separately with the real helper and late
standalone attachment. Their capture convention remains backward-compatible.

## Completion safety and remaining scope limits

Interrupted capture, unread backlog, missing EOF, foreign/repeated package
streams, or multiple deployment processes cannot certify per-CLI completion.
The full parent task stream remains available when individual task executions
cannot be attributed safely. Process metadata polling does not manufacture
historical child process identities. Raw native status remains unknown after
late attachment; green completion is only the documented evidence-based UI
inference, including the approved final Helm-health rule.

The 16 UI assets are unchanged and remain byte-identical to the approved source.
No remote OCI-only support, Windows support, permanent capture history, singleton
viewer migration, or broad future-CLI certification is implied.

## Reproduce

See README for native/unit, real SDK and journey commands. Set
`UDS_JOURNEY_API_ONLY=1` only for API-only checks. Build bootstrap source with
`scripts/build-cli-bootstrap.py --output /tmp/uds-watch-bootstrap` and use
`UDS_BOOTSTRAP_TEST_BINARY=/tmp/uds-watch-bootstrap` with the native fixture tests
to check a fresh development build separately from the pinned distribution.
This override exists only in test code, never runtime setup.
