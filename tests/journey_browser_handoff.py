"""Test-only URL recorder; never launches an OS browser or Chromium.

Normal Playwright launch is used by the driver. Always exit zero so an inability
to record cannot cause webbrowser to fall back to the user's platform browser.
A missing record makes the journey test fail instead.
"""
import json
import os
from pathlib import Path
import sys

if __name__=='__main__':
    try:
        event=Path(os.environ['UDS_JOURNEY_BROWSER_EVENT'])
        fd=os.open(event,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:json.dump({'url':sys.argv[1]},stream)
    except Exception:pass
    raise SystemExit(0)
