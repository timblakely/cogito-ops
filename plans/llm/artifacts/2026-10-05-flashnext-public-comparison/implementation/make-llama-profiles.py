import json,yaml,copy
from pathlib import Path
r=Path('/home/tim/git/cogito/kubernetes/apps/llm/llmkube/resources/manual');out=Path('/tmp/flashnext-competition')
q4=next(d for d in yaml.safe_load_all((r/'flashnext-iggy-q4-rdna4.yaml').read_text()) if d['kind']=='InferenceService')['spec']
q6=next(d for d in yaml.safe_load_all((r/'flashnext-iggy-q6-c2.yaml').read_text()) if d['kind']=='InferenceService')['spec']
def pod(name,spec):
 c={'name':'runtime','image':spec['image'],'command':['/bin/bash','-ec','cd /workspace/flashnext-competition/stew; exec build/bin/llama-server "$@"','flashnext'],'args':spec['args'],'env':[e for e in spec['env'] if e['name'] in ('LD_LIBRARY_PATH','OMP_WAIT_POLICY')], 'resources':{'requests':{'cpu':'8','memory':'80Gi','amd.com/gpu':2},'limits':{'memory':'110Gi','amd.com/gpu':2}},'volumeMounts':[{'name':v['name'],'mountPath':v['mountPath']} for v in spec['extraVolumeMounts']], 'readinessProbe':{'httpGet':{'path':'/health','port':8080},'periodSeconds':10}}
 vols=copy.deepcopy(spec['extraVolumes']);names={v['name'] for v in vols}
 for n,m,claim in [('archive','/archive','llm-model-archive'),('ngram','/ngram','flashnext-iggy-ngram')]:
  if n not in names:vols.append({'name':n,'persistentVolumeClaim':{'claimName':claim}});c['volumeMounts'].append({'name':n,'mountPath':m})
 return {'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':'llm'},'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'nodeSelector':{'kubernetes.io/hostname':'iggy'},'tolerations':[{'key':k,'operator':'Exists','effect':'NoSchedule'} for k in ('node-role.kubernetes.io/control-plane','amd.com/gpu')],'securityContext':{'seccompProfile':{'type':'Unconfined'}},'containers':[c],'volumes':vols}}
def setarg(c,k,v):
 a=c['args']
 if k in a:a[a.index(k)+1]=str(v)
 else:a.extend([k,str(v)])
for name in ('stew-q4-baseline','stew-q4-cache','stew-q4-public-single','stew-q4-public-mtp','stew-q6-cache'):
 p=pod('flashnext-'+name,q6 if 'q6' in name else q4);c=p['spec']['containers'][0]
 c['env']+=[{'name':'GGML_SCHED_DEVGATHER','value':'0'}]
 if name=='stew-q4-baseline':c['env'] += [{'name':'MOE_EXPERT_CACHE_MIB','value':'0'},{'name':'GGML_CUDA_NO_PINNED','value':'1'}]
 else:
  setarg(c,'--lazy-mode','on');setarg(c,'--load-mode','mmap');setarg(c,'--ctx-size','262144');setarg(c,'--parallel','2');setarg(c,'--cache-ram','2048');setarg(c,'--ctx-checkpoints','0')
  setarg(c,'--override-tensor','per_layer_token_embd=CPU');setarg(c,'--n-cpu-moe','38' if 'q6' in name else '32');setarg(c,'--split-mode','tensor');setarg(c,'--tensor-split','1,1');setarg(c,'--batch-size','4096');setarg(c,'--ubatch-size','2048');setarg(c,'--threads-batch','12')
  c['env'] += [{'name':'MOE_EXPERT_CACHE_DEVMAP','value':'1'},{'name':'MOE_EXPERT_CACHE_RESERVE_MIB','value':'1024'}]
  if 'public' in name:
   setarg(c,'--load-mode','none')
   c['env'] += [{'name':'MOE_EXPERT_CACHE_MIB','value':'4096'},{'name':'ROCR_VISIBLE_DEVICES','value':'1'},{'name':'HIP_VISIBLE_DEVICES','value':'0'}];c['resources']['requests']['amd.com/gpu']=2;c['resources']['limits']['amd.com/gpu']=2
   setarg(c,'--n-cpu-moe','47' if 'mtp' in name else '41');setarg(c,'--split-mode','layer');setarg(c,'--tensor-split','1');setarg(c,'--threads','6');setarg(c,'--threads-batch','6');setarg(c,'--batch-size','2048');setarg(c,'--ubatch-size','512')
  if name=='stew-q4-public-mtp': c['args']+=['--spec-draft-model','/models/mtp/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf','--spec-draft-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','3']
 (out/(name+'.json')).write_text(json.dumps(p,indent=2)+'\n')
print('Rendered five private llama profiles')
