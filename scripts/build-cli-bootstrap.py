#!/usr/bin/env python3
"""Developer build only. Registration uses bundled bootstrap executables, not cc."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--arch',default=platform.machine())
parser.add_argument('--output',type=Path)
parser.add_argument('--refresh-manifest',action='store_true',help='explicitly pin all four reviewed artifacts after their builds')
args=parser.parse_args()
arch={'amd64':'x86_64','arm64':'arm64' if sys.platform=='darwin' else 'aarch64'}.get(args.arch,args.arch)
output=args.output or ROOT/'src/uds_deploy/bootstrap'/(sys.platform+'-'+arch)
output.parent.mkdir(parents=True,exist_ok=True)
flags=['-O2','-Wall','-Wextra','-Werror']
if sys.platform=='darwin':flags+=['-arch',arch,'-mmacosx-version-min='+('11.0' if arch=='arm64' else '10.15')]
subprocess.run(['cc']+flags+[str(ROOT/'src/uds_deploy/cli_bootstrap.c'),'-o',str(output)],check=True)
print('Built '+output.name)
if args.refresh_manifest:
    home=ROOT/'src/uds_deploy/bootstrap'
    names=['darwin-arm64','darwin-x86_64','linux-aarch64','linux-x86_64']
    manifest={'schema_version':1,'source_sha256':hashlib.sha256((ROOT/'src/uds_deploy/cli_bootstrap.c').read_bytes()).hexdigest(),'sha256':{name:hashlib.sha256((home/name).read_bytes()).hexdigest() for name in names}}
    (home/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
