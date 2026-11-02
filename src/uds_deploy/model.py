"""Read-only model helpers, adapted from the Apache-2.0 watcher; see NOTICE."""
from .definitions import declared_charts

KINDS = {
    'cluster.connect':'Connect to Kubernetes', 'actions.before':'Pre-deploy actions',
    'actions.after':'Post-deploy actions', 'actions.success':'Success actions',
    'actions.failure':'Failure actions', 'files.copy':'Copy files', 'images.push':'Push images',
    'repositories.push':'Push Git repositories', 'data.inject':'Inject data',
    'helm.apply':'Helm operation', 'helm.install':'Helm install', 'helm.upgrade':'Helm upgrade',
    'helm.rollback':'Helm rollback', 'health.wait':'Resource readiness',
    'health.component':'Component health checks', 'manifests.apply':'Deploy manifests',
}


def package_by_id(state, name):
    return next(package for package in state['packages'] if package['id'] == name)


def phase_model(spec):
    resource = spec.get('resource', {})
    if not isinstance(resource, dict) or set(resource) - {'chart','namespace','release','count','manifest'}:
        raise ValueError('Unsupported resource fields')
    if spec.get('kind') not in KINDS or not isinstance(spec.get('id'), str):
        raise ValueError('Unsupported operation definition')
    for key, value in resource.items():
        if key == 'count':
            if type(value) is not int or value < 0:
                raise ValueError('Invalid resource count')
        elif not isinstance(value, str) or len(value) > 2048:
            raise ValueError('Invalid resource identity')
    if type(spec.get('conditional', False)) is not bool:
        raise ValueError('Invalid conditional definition')
    identity = resource.get('chart') or resource.get('release')
    label = KINDS[spec['kind']] + (': ' + identity if identity else '')
    return dict(id=spec['id'], kind=spec['kind'], label=label, resource=resource,
                conditional=spec.get('conditional', False), expected=True, observed=False,
                status='pending', started_at=None, completed_at=None, error=None, executions=[])


def definition_operations(component, package_name=None):
    """Packaged declarations are not evidence that work actually executed."""
    phases = []
    def add(identity, kind, resource=None):
        phases.append(phase_model(dict(id=identity, kind=kind, resource=resource or {}, conditional=True)))
    actions = component.get('actions', {}).get('onDeploy', {})
    for key, kind in [('before','actions.before'),('after','actions.after'),('onSuccess','actions.success'),('onFailure','actions.failure')]:
        if actions.get(key):add(kind, kind)
    for field, kind in [('images','images.push'),('files','files.copy'),('repos','repositories.push'),('manifests','manifests.apply'),('dataInjections','data.inject'),('healthChecks','health.component')]:
        if component.get(field):add(kind, kind, {'count':len(component[field])})
    for chart in declared_charts(component, package_name):
        resource = {key:chart[key] for key in ('name','namespace','manifest') if key in chart}
        resource['chart'] = resource.pop('name', 'chart')
        resource['release'] = chart.get('releaseName') or resource['chart']
        add('helm:' + resource['chart'], 'helm.apply', resource)
        if not chart.get('skipWait'):add('health:' + resource['chart'], 'health.wait', resource)
    return phases
