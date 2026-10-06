import json,subprocess
from pathlib import Path
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','--request-timeout=10s']
def read(args):return json.loads(subprocess.check_output(k+args,timeout=20))
node=read(['get','node','amnesia','-o','json']);pods=read(['-n','llm','get','pods','-l','app=flashnext','-o','json'])['items'];events=[]
for p in pods:events+=read(['-n','llm','get','events','--field-selector','involvedObject.uid='+p['metadata']['uid'],'-o','json'])['items']
proof={'node_conditions':node['status']['conditions'],'node_gpu_allocatable':{k:v for k,v in node['status'].get('allocatable',{}).items() if 'gpu' in k},'pods':[{'name':p['metadata']['name'],'phase':p['status']['phase'],'conditions':p['status'].get('conditions',[]),'nodeSelector':p['spec'].get('nodeSelector'),'gpu_requests':[{k:v for k,v in c.get('resources',{}).get('requests',{}).items() if 'gpu' in k} for c in p['spec']['containers']]} for p in pods],'events':[{'reason':e['reason'],'message':e['message']} for e in events]};Path('/tmp/flashnext-competition/amnesia-post-campaign-status.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof))
