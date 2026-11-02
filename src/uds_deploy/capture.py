"""Output-only helper: this file never launches a deployment."""
from pathlib import Path
import signal
import sys

# Direct file execution keeps the capture helper identifiable to the observer.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from uds_deploy.output import copy_output


def main():
    if sys.argv[1:2]==['--check-command']:
        from uds_deploy.native import command_args
        tool=sys.argv[2] if len(sys.argv)>2 else ''
        args=command_args([tool]+sys.argv[3:])
        direct=tool=='uds' and (args[:1] in (['deploy'],['d']) or args[:3]==['zarf','package','deploy']) or tool=='zarf' and args[:2]==['package','deploy']
        return 0 if direct else 1
    # Let the native CLI handle Ctrl+C and drain its final cleanup messages.
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    return copy_output(sys.stdin.buffer,sys.stdout.buffer)


if __name__=='__main__':raise SystemExit(main())
