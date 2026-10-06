"""Convert a qualified private llama Pod into a suspended catalogue preset."""
import argparse,copy,json,re
from pathlib import Path
import yaml
p=argparse.ArgumentParser();p.add_argument('pod',type=Path);p.add_argument('--name',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert re.fullmatch(r'[0-9a-f]{64}',a.manifest_sha256)
root=Path('/home/tim/git/cogito/kubernetes/apps/llm/llmkube/resources/manual');base=list(yaml.safe_load_all((root/'flashnext-iggy-q6-c2.yaml').read_text()));pod=json.loads(a.pod.read_text());c=pod['spec']['containers'][0];service=copy.deepcopy(base[1]);s=service['spec'];service['metadata']['name']=a.name;s['image']=c['image'];s['args']=c['args'];s['env']=c['env']+[{'name':'FLASHNEXT_BUILD_MANIFEST_SHA256','value':a.manifest_sha256}]
cmd=c['command'];match=re.fullmatch(r'cd (/workspace/[^;]+); exec build/bin/llama-server "\$@"',cmd[2]);assert match,cmd
s['command']=[cmd[0],cmd[1],f'cd {match[1]}; printf \'%s  build.sha256\\n\' "$FLASHNEXT_BUILD_MANIFEST_SHA256" | sha256sum -c - >&2; sha256sum -c build.sha256 >&2; exec build/bin/llama-server "$@"',cmd[3]]
s['resources']['memory']=c['resources']['limits']['memory'];s['resources']['cpu']=c['resources']['requests']['cpu'];s['resources']['gpu']=2
assert all(set(v)=={'name','persistentVolumeClaim'} for v in pod['spec']['volumes']);s['extraVolumes']=pod['spec']['volumes'];s['extraVolumeMounts']=[{**m,'readOnly':True} for m in c['volumeMounts']]
s['suspend']=True;assert s['args'][s['args'].index('--model')+1].startswith('/models/q6/')
a.output.write_text('# Qualified Q6 profile; all model shards use checksum-verified local NVMe copies.\n'+yaml.safe_dump_all([base[0],service],sort_keys=False));print('PRESET_RENDERED',a.output)
