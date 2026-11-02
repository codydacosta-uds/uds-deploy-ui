"""Standalone read-only projection, adapted from Apache-2.0 code; see NOTICE."""
from .model import KINDS


def view(state):
    by_id = {p['id']: p for p in state['packages']}
    depths = {}
    visiting = set()
    def depth(name):
        if name in depths:
            return depths[name]
        if name in visiting:
            raise ValueError('Saved deployment plan contains a cycle')
        visiting.add(name)
        value = 0
        for parent in by_id[name]['dependencies']:
            if parent not in by_id:
                raise ValueError('Saved deployment plan has an unknown prerequisite')
            value = max(value, depth(parent)+1)
        visiting.remove(name)
        depths[name] = value
        return value
    for p in state['packages']:
        depth(p['id'])
        current = p['attempts'][-1] if p['attempts'] else {}
        execution = current.get('execution')
        p['execution'] = execution or dict(schema_version=0, observation='legacy' if p['attempts'] else 'awaiting', components=[])
        p['pipeline_depth'] = depths[p['id']]
        active = [(c['id'], phase['label']) for c in p['execution']['components'] for phase in c['phases'] if phase['status'] == 'running']
        components_running = [c['id'] for c in p['execution']['components'] if c['status'] == 'running']
        if p['status'] == 'completed':
            p['current_activity'] = 'Deployment completed'
        elif p['status'] in ('failed','cancelled','unknown'):
            p['current_activity'] = p['error'] or ('Outcome indeterminate' if p['status'] == 'unknown' else p['status'])
        elif active:
            p['current_activity'] = active[0][1] if len(active) == 1 else '{} operations running'.format(len(active))
        elif components_running:
            p['current_activity'] = 'Component {} running; next operation not yet reported'.format(components_running[0])
        elif p['status']=='deploying' and p['execution'].get('observation') in ('unavailable','definition-only'):
            p['current_activity']='UDS command running · detailed step outcomes unavailable'
        elif p['status'] == 'deploying':
            p['current_activity'] = 'Package execution running; waiting for the next boundary' if current.get('package_started_at') else 'UDS command running; waiting for execution events'
        else:
            p['current_activity'] = 'Waiting for execution' if not p['dependencies'] else 'Waiting for prerequisites'
        p['tracking_notice'] = (
            'This attempt predates typed execution tracking. No component or operation results are reconstructed from its logs.' if not execution and p['attempts'] else
            'Stock CLI: only invocation/package results are verifiable. Detailed execution events are unavailable.' if execution and execution.get('observation') == 'unavailable' else
            'Some execution events are missing. Unverified operation outcomes remain unknown.' if execution and execution.get('observation') == 'partial' else ''
        )
    groups = []
    for level in sorted(set(depths.values())):
        members = [p['id'] for p in state['packages'] if depths[p['id']] == level]
        groups.append(dict(id=level, label='Dependency group '+str(level+1), packages=members,
                           concurrent=len(members)>1 and state['mode']=='concurrent'))
    state['pipeline'] = dict(schema_version=1, groups=groups, operation_labels=KINDS,
                             description='Definition grouping, not proof of execution or completion')
    return state
