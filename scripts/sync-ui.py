#!/usr/bin/env python3
"""Sync the one shared viewer UI, or reject drift. Development-only; stdlib only."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
ALLOWED={'.html','.js','.css','.png','.woff2','.txt'}


def inventory(directory):
    result={}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():raise ValueError('Shared UI assets cannot be symlinks')
        if not path.is_file():continue
        if path.name=='.DS_Store' or '__pycache__' in path.parts:continue
        if path.suffix not in ALLOWED and path.name!='.gitattributes':raise ValueError('Unexpected shared UI file: '+str(path.relative_to(directory)))
        result[str(path.relative_to(directory))]=hashlib.sha256(path.read_bytes()).hexdigest()
    if not {'app.js','index.html','style.css','theme.css','theme.js','uds-logo.png','uds-logo-on-dark.png'}<=result.keys():raise ValueError('Incomplete shared viewer UI')
    return result


def manifest(files):return {'schema_version':1,'description':'Shared deployment viewer UI: identical HTML, JavaScript, CSS, fonts and artwork in every consumer.','files':files}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,help='approved UI source directory; required when refreshing or copying')
    parser.add_argument('--manifest',type=Path,default=ROOT/'ui-assets.json')
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--destination-manifest',type=Path)
    parser.add_argument('--refresh-manifest',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:
        if (args.refresh_manifest or args.destination) and args.source is None:raise ValueError('Supply the approved UI branch directory with --source; do not independently edit the vendor copy')
        source=args.source or ROOT/'src/uds_deploy/web'
        files=inventory(source)
        if args.refresh_manifest:
            if args.check or args.destination:raise ValueError('Refresh the canonical manifest separately before synchronizing consumers')
            args.manifest.write_text(json.dumps(manifest(files),indent=2)+'\n')
            print('Updated shared UI manifest: '+str(len(files))+' assets');return
        expected=json.loads(args.manifest.read_text())
        if expected!=manifest(files):raise ValueError('Canonical UI differs from its manifest. Review the change, then use --refresh-manifest and sync every consumer.')
        if not args.destination:
            print('Shared UI manifest verified: '+str(len(files))+' assets');return
        destination=args.destination
        if not destination.is_dir() or destination.name!='web' or destination.resolve()==source.resolve():raise ValueError('Choose a different existing viewer web directory')
        if args.check:
            if inventory(destination)!=files:raise ValueError('UI drift detected in consumer')
            if args.destination_manifest and json.loads(args.destination_manifest.read_text())!=expected:raise ValueError('Consumer manifest differs')
            print('No UI drift: '+str(len(files))+' assets are byte-for-byte identical');return
        if not args.destination_manifest:raise ValueError('Supply --destination-manifest explicitly when synchronizing')
        extra=set(inventory(destination))-set(files)
        if extra:raise ValueError('Consumer has extra UI files; review them before syncing: '+', '.join(sorted(extra)))
        for name in files:
            target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
        args.destination_manifest.write_text(json.dumps(expected,indent=2)+'\n')
        if inventory(destination)!=files:raise ValueError('Consumer verification failed')
        print('Synchronized '+str(len(files))+' shared UI assets; consumer manifest updated')
    except (OSError,ValueError) as error:parser.error(str(error))


if __name__=='__main__':main()
