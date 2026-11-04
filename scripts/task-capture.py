#!/usr/bin/env python3
"""Add/remove the existing capture tee in an explicitly selected UDS task file."""
from pathlib import Path
import re
import sys

PIPE=' 2>&1 | ("$HOME/.local/bin/uds-watch" capture || cat)'
EXIT='exit "${PIPESTATUS[0]}" # uds-watch capture'
HEADER='- cmd: | # uds-watch capture'
DEPLOY=re.compile(r'(?:\./)?(?:uds(?: zarf package)?|zarf package) (?:deploy|d)\b')


def configure(path,remove=False,check=False):
    original=path.read_bytes().decode('utf-8');newline='\r\n' if '\r\n' in original else '\n'
    lines=original.splitlines();out=[];i=0;found=0
    while i<len(lines):
        line=lines[i];text=line.lstrip();indent=line[:len(line)-len(text)]
        if remove and text==HEADER:
            expected=[indent+'    '+EXIT,indent+'  shell:',indent+'    linux: bash',indent+'    darwin: bash']
            if i+5>=len(lines) or not lines[i+1].endswith(PIPE) or lines[i+2:i+6]!=expected:raise ValueError('Managed capture action was edited; remove its hook manually')
            out.append(indent+'- cmd: '+lines[i+1].strip()[:-len(PIPE)]);i+=6;continue
        if remove and line.endswith(PIPE):
            if i+1>=len(lines) or lines[i+1].strip()!=EXIT:raise ValueError('Managed capture exit was edited; repair it before uninstalling')
            out.append(line[:-len(PIPE)]);i+=2;continue
        inline=text.startswith('- cmd: ');command=text[len('- cmd: '):] if inline else text
        if not remove and DEPLOY.match(command):
            found+=1
            if PIPE in command or 'scripts/deploy-output.py' in command:
                out.append(line);i+=1;continue  # Existing capture stays configured.
            following=next((row for row in lines[i+1:] if row.strip()),'')
            if following and len(following)-len(following.lstrip())>=(len(indent)+1 if inline else len(indent)):
                raise ValueError('Deployment must be the final command of its task action')
            if not inline:
                shell_at=lines.index(following,i+1) if following else len(lines)
                if following.strip()!='shell:' or {row.strip() for row in lines[shell_at+1:shell_at+3]}!={'linux: bash','darwin: bash'}:raise ValueError('Multi-line deployment actions must explicitly use Bash')
            if inline:
                out.extend([indent+HEADER,indent+'    '+command+PIPE,indent+'    '+EXIT,indent+'  shell:',indent+'    linux: bash',indent+'    darwin: bash'])
            else:
                out.extend([line+PIPE,indent+EXIT])
        else:out.append(line)
        i+=1
    if not remove and not found:raise ValueError('No supported UDS/Zarf deployment actions found')
    updated=newline.join(out)+(newline if original.endswith(('\n','\r')) else '')
    if updated!=original and not check:path.write_bytes(updated.encode('utf-8'))
    return updated!=original


if __name__=='__main__':
    try:
        changed=configure(Path(sys.argv[2]),remove=sys.argv[1]=='uninstall',check='--check' in sys.argv[3:])
        if '--check' not in sys.argv[3:]:print(('Removed managed capture from ' if sys.argv[1]=='uninstall' else 'Capture configured in ')+sys.argv[2])
    except (OSError,ValueError) as error:raise SystemExit(str(error))
