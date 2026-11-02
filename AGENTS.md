# Development rules

- This tool is strictly read-only. Never add deployment launch, retry, cancellation, scheduling, process signalling, or mutation APIs. The optional shell function calls the native CLI; capture only copies stdin.
- Never read a TTY, terminal scrollback, or another process's deployment pipe. Inspect only same-user process metadata, packaged artifacts, and validated capture files.
- Preserve original command arguments, terminal output bytes, native exit status, and Ctrl+C behavior. Test Bash and zsh integration explicitly.
- Keep the Python runtime stdlib-only and frontend build-free. No external fonts/scripts, database, credential snapshots, or installed background service.
- Display complete packaged YAML and commands. Do not snapshot external resolved config or live credentials. Keep unknown outcomes unknown; CLI exit/disappearance alone is not success. Green completion inferred from error-free sequential CLI advancement is intentional and must remain explained.
- UI changes require Playwright checks on real captures, screenshot inspection, both themes, and responsive widths. Re-run after the final edit. Synthetic edge tests must be identified as isolated tests, not live evidence. Never redeploy real applications for styling.
- Keep tests isolated. Do not stop user-owned viewers or lose held captures. Clean up temporary test browsers and servers.
- Conventional Commit messages and PR titles are required. Never update the repository's default branch; use feature branches and PRs. No secrets, local captures, CLI binaries, or private capability URLs in commits or diagnostics.
