"""Verify the published revision, restored holds and live Native workload."""
import argparse,json,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('revision');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443']
def get(ns,kind,name=None,extra=()):
 return json.loads(subprocess.check_output(k+['-n',ns,'get',kind]+([name] if name else [])+list(extra)+['-o','json']))
def ready(j):return any(c['type']=='Ready' and c['status']=='True' for c in j['status'].get('conditions',[]))
source=get('flux-system','gitrepository','flux-system');ks=get('llm','kustomization','llmkube-resources');svc=get('llm','inferenceservice','flashnext-iggy');dep=get('llm','deployment','flashnext-iggy');pods=get('llm','pods',extra=('-l','app=flashnext-iggy'))['items'];live=[x for x in pods if not x['metadata'].get('deletionTimestamp')];amnesia=get('llm','pods',extra=('-l','app=flashnext'))['items']
expected='docker.io/stilldeadcode/radiance:1.0.13@sha256:4c3f484564bb2872784e46b0a59cbd71becc9c1e746e301a3596ffae253c322e';revision='refs/heads/main@sha1:'+a.revision
checks={'source_revision':source['status']['artifact']['revision']==revision,'source_ready':ready(source),'applied_revision':ks['status']['lastAppliedRevision']==revision,'kustomization_ready':ready(ks),'kustomization_resumed':not ks['spec'].get('suspend',False),'kustomization_hold_removed':ks['metadata'].get('annotations',{}).get('kustomize.toolkit.fluxcd.io/reconcile')!='disabled','service_resumed':not svc['spec'].get('suspend',False),'service_hold_removed':svc['metadata'].get('annotations',{}).get('kustomize.toolkit.fluxcd.io/reconcile')!='disabled','service_image':svc['spec']['image']==expected,'deployment_ready':dep['status'].get('readyReplicas',0)==1 and dep['status'].get('observedGeneration',0)>=dep['metadata']['generation'],'one_live_pod':len(live)==1}
records=[]
for pod in live:
 c=next(x for x in pod['spec']['containers'] if x['name']=='inference-server');args=c['args'];arg=lambda f:args[args.index(f)+1];status=next(x for x in pod['status']['containerStatuses'] if x['name']==c['name']);values={'name':pod['metadata']['name'],'node':pod['spec']['nodeName'],'image':c['image'],'image_id':status.get('imageID'),'ready':status['ready'],'restart_count':status['restartCount'],'gpu_limit':c['resources']['limits'].get('amd.com/gpu'),'args':args};records.append(values);checks.update(pod_ready=status['ready'],pod_on_iggy=values['node']=='iggy',pod_image=c['image']==expected,pod_gpu_two=str(values['gpu_limit'])=='2',ngram_disk=arg('--ngram-placement')=='disk',tp_exact=arg('--tp')=='2' and arg('--tp-wire')=='exact',production_two_slots=arg('--max-num-seqs')=='2',production_context=arg('--max-model-len')=='262144')
storage=[]
for record in records:
 mountinfo=subprocess.check_output(k+['-n','llm','exec',record['name'],'-c','inference-server','--','/usr/bin/busybox','cat','/proc/self/mountinfo'],text=True)
 mounts=[line for line in mountinfo.splitlines() if ' /models ' in line]
 model_stat=subprocess.check_output(k+['-n','llm','exec',record['name'],'-c','inference-server','--','/usr/bin/busybox','stat','-c','%s %i','/models/radiance/qwen3.8-next-flash-fp8-iq4r-moe.rad'],text=True).strip()
 checks['live_model_nvme_mount']=len(mounts)==1 and '/dev/nvme0n1p1' in mounts[0]
 checks['live_model_bytes']=model_stat.split()[0]=='121969901568'
 storage.append({'pod':record['name'],'mountinfo':mounts,'model_bytes_inode':model_stat,'description':'RAD includes the original n-gram table; disk-placement flag and actual local NVMe mount are both checked'})
proof={'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'revision':a.revision,'storage':storage,'checks':checks,'pods':records,'source_revision':source['status']['artifact']['revision'],'applied_revision':ks['status']['lastAppliedRevision'],'amnesia_model_pods':[{'name':x['metadata']['name'],'node':x['spec'].get('nodeName'),'phase':x['status']['phase'],'ready':ready(x),'restart_counts':[c['restartCount'] for c in x['status'].get('containerStatuses',[])]} for x in amnesia]}
a.output.write_text(json.dumps(proof,indent=2)+'\n');print('PRODUCTION_VERIFICATION',checks);assert all(checks.values()),'Production verification incomplete; inspect retained proof'
