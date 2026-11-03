"""Output-only helper: this file never launches a deployment."""
from pathlib import Path
import signal
import sys

# Direct file execution keeps the capture helper identifiable to the observer.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from uds_deploy.output import copy_output


def main():
    # Obsolete shell-hook probes must fall through to native, not consume stdin.
    if len(sys.argv)>1:return 1
    # Let the native CLI handle Ctrl+C and drain its final cleanup messages.
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    return copy_output(sys.stdin.buffer,sys.stdout.buffer)


if __name__=='__main__':raise SystemExit(main())
