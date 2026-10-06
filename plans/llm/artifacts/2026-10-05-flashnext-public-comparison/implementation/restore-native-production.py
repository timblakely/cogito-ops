"""Remove scoped benchmark holds after the authorized revision is fetched; verify service."""
import json,subprocess,sys,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');sha='896ac30bff32f3b7b5999670c2b0dcc834f6969c';kub='/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl';flux='/home/tim/.local/share/mise/installs/aqua-fluxcd-flux2/2.7.3/flux';opts=['--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443'];k=[kub,*opts,'--request-timeout=15s'];f=[flux,*opts,'--timeout=4m'];expected='docker.io/stilldeadcode/radiance:1.0.13@sha256:4c3f484564bb2872784e46b0a59cbd71becc9c1e746e301a3596ffae253c322e'
def get(ns,kind,name):return json.loads(subprocess.check_output(k+['-n',ns,'get',kind,name,'-o','json'],timeout=25))
def call(args):subprocess.run(args,check=True)
source=get('flux-system','gitrepository','flux-system');print('SOURCE_REF',source['spec']['ref'],flush=True);assert (source['spec']['ref'].get('branch') or source['spec']['ref'].get('name')) in ('main','refs/heads/main');call(f+['reconcile','source','git','flux-system','-n','flux-system']);source=get('flux-system','gitrepository','flux-system');assert source['status']['artifact']['revision']=='refs/heads/main@sha1:'+sha
for ns,kind,name in [('llm','inferenceservice','flashnext-iggy'),('llm','kustomization','llmkube-resources')]:
 obj=get(ns,kind,name)
 if obj['metadata'].get('annotations',{}).get('kustomize.toolkit.fluxcd.io/reconcile')=='disabled':call(k+['-n',ns,'annotate',kind,name,'kustomize.toolkit.fluxcd.io/reconcile-'])
call(k+['-n','llm','patch','kustomization','llmkube-resources','--type=merge','-p',json.dumps({'spec':{'suspend':False}})])
call(f+['reconcile','kustomization','llmkube-resources','-n','llm','--with-source'])
for attempt in range(100):
 dep=get('llm','deployment','flashnext-iggy');pods=json.loads(subprocess.check_output(k+['-n','llm','get','pods','-l','app=flashnext-iggy','-o','json'],timeout=25))['items'];live=[p for p in pods if not p['metadata'].get('deletionTimestamp')]
 status=[(p['metadata']['name'],p['status']['phase'],[(c['name'],c.get('ready'),c.get('restartCount')) for c in p['status'].get('containerStatuses',[])]) for p in live];print('WAIT_NATIVE_PRODUCTION',status,flush=True)
 if dep['status'].get('readyReplicas')==1 and len(live)==1 and all(c.get('ready') for c in live[0]['status'].get('containerStatuses',[])) and live[0]['spec']['containers'][0]['image']==expected:break
 time.sleep(10)
else:raise SystemExit('Native production did not reach readiness; inspect current Pod before changing this same task')
call(['/usr/bin/python3',str(r/'verify-production.py'),sha,'--output',str(r/'production-deployment-verification.json')]);call(['/usr/bin/python3',str(r/'production-smoke.py')]);print('PRODUCTION_RESTORED_AND_ALIAS_VERIFIED',sha,flush=True)
