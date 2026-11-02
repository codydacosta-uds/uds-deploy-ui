# Standalone adaptation of Apache-2.0 watcher code; see NOTICE.
"""Read-only packaged artifact views; never snapshot resolved deployment config."""
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

HIDDEN='[value hidden]'
# Legacy masked-capture compatibility only. New definition views and captures
# retain the complete packaged document, not this structural projection.
CONTAINERS={'metadata','build','packages','components','charts','images','only'}
SCALARS={'kind','name','version','architecture','flavor','namespace','releaseName','ref','repository','url','required','optional','skipWait'}


def safe_reference(value):
    if not isinstance(value,str):return value
    if '://' not in value:return value
    parsed=urlsplit(value)
    host=parsed.netloc.rsplit('@',1)[-1]
    return urlunsplit((parsed.scheme,host,parsed.path,'',''))


def redact_definition(value):
    if isinstance(value,list):return [redact_definition(item) for item in value]
    if not isinstance(value,dict):return safe_reference(value)
    result={}
    for key,item in value.items():
        if key in CONTAINERS and isinstance(item,(dict,list)):result[key]=redact_definition(item)
        elif key in SCALARS and isinstance(item,(str,int,float,bool,type(None))):result[key]=safe_reference(item)
        else:result[key]=HIDDEN
    return result


def yaml_text(document):
    """Emit the JSON-compatible YAML subset; never evaluate YAML or shell code."""
    def scalar(value):return json.dumps(value,ensure_ascii=True,allow_nan=False)
    def key(value):return value if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*',value) and value not in ('true','false','null') else scalar(value)
    def lines(value,indent=0):
        pad=' '*indent;out=[]
        if isinstance(value,dict) and value:
            for name,item in value.items():
                if isinstance(item,(dict,list)) and item:
                    out.append(pad+key(name)+':');out.extend(lines(item,indent+2))
                else:out.append(pad+key(name)+': '+scalar(item))
        elif isinstance(value,list) and value:
            for item in value:
                if isinstance(item,(dict,list)) and item:
                    child=lines(item,indent+2);out.append(pad+'- '+child[0].lstrip());out.extend(child[1:])
                else:out.append(pad+'- '+scalar(item))
        else:out.append(pad+scalar(value))
        return out
    return '\n'.join(lines(document))+'\n'


def artifact_info(definition=None,reference=None):
    definition=definition or {};metadata=definition.get('metadata',{});build=definition.get('build',{})
    info={}
    architecture=metadata.get('architecture') or build.get('architecture')
    if architecture:info['architecture']=architecture
    if metadata.get('version'):info['version']=str(metadata['version'])
    if reference:
        info['reference']=safe_reference(reference)
        if '@sha256:' in reference:info['digest']='sha256:'+reference.rsplit('@sha256:',1)[1]
    info['has_yaml']=definition.get('kind') in ('UDSBundle','ZarfPackageConfig','ZarfInitConfig')
    if info['has_yaml']:info['kind']=definition['kind']
    return info


def declared_charts(component,package_name=None):
    """Packaged charts plus Zarf's exact manifest-to-Helm identity projection.

    Zarf v0.88 ChartFromZarfManifest: chart raw-PACKAGE-COMPONENT-MANIFEST,
    release zarf-SHA1(chart), namespace defaults to default. Not execution proof.
    """
    charts=[dict(chart) for chart in component.get('charts',[])]
    if package_name:
        for manifest in component.get('manifests',[]):
            if not manifest.get('name'):continue
            name='raw-{}-{}-{}'.format(package_name,component['name'],manifest['name'])
            charts.append(dict(name=name,releaseName='zarf-'+hashlib.sha1(name.encode()).hexdigest(),namespace=manifest.get('namespace') or 'default',skipWait=manifest.get('skipWait',False),manifest=manifest['name']))
    return charts


def component_info(component,package_name=None):
    info={}
    if component.get('images'):info['images']=[safe_reference(image) for image in component['images']]
    charts=[]
    for chart in declared_charts(component,package_name):
        item={key:chart[key] for key in ('name','namespace','version','manifest') if chart.get(key) is not None}
        item['release']=chart.get('releaseName') or chart['name'];charts.append(item)
    if charts:info['charts']=charts
    return info


def document_view(document,values_hidden=False):
    kind=document.get('kind')
    if kind not in ('UDSBundle','ZarfPackageConfig','ZarfInitConfig'):raise KeyError('Packaged definition unavailable')
    return dict(filename='uds-bundle.yaml' if kind=='UDSBundle' else 'zarf.yaml',yaml=yaml_text(document),values_hidden=values_hidden)
