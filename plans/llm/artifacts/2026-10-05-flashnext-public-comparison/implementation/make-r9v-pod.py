import json
from pathlib import Path
base=Path('/tmp/flashnext-competition')
a=json.loads((base/'r9v-launch-args.json').read_text())
image='r9v-qwen38-flash-next-wmma:20260915-r2';idx=a.index("sha256:2dac17a215fb5b0e3461e4c3e36a2981eec8ac3d6021e73183d247e819740c03")
env=[];mounts=[];vols=[];volume_for_claim={}
for i,v in enumerate(a[:idx]):
    if v=='--env':
        n,val=a[i+1].split('=',1);env.append({'name':n,'value':val})
    if v=='--volume':
        source,target,*mode=a[i+1].split(':');read_only='ro' in mode
        if source.startswith('/archive/'):
            claim='llm-model-archive';sub=source.removeprefix('/archive/')
        elif source.startswith('/ngram/'):
            claim='flashnext-iggy-ngram';sub=source.removeprefix('/ngram/')
        elif source.startswith('/workspace/'):
            claim='cuda-dev-workspace';sub=source.removeprefix('/workspace/')
        else:raise RuntimeError('unadapted volume '+source)
        if claim not in volume_for_claim:
            n='mount'+str(len(vols));volume_for_claim[claim]=n;vols.append({'name':n,'persistentVolumeClaim':{'claimName':claim}})
        n=volume_for_claim[claim]
        mounts.append({'name':n,'mountPath':target,'subPath':sub,'readOnly':read_only})
vols.append({'name':'shm','emptyDir':{'medium':'Memory','sizeLimit':'32Gi'}})
mounts.append({'name':'shm','mountPath':'/dev/shm'})
c={'name':'runtime','image':'docker.io/library/'+image,'imagePullPolicy':'Never','args':a[idx+1:],'env':env,'volumeMounts':mounts,
   'resources':{'requests':{'cpu':'8','memory':'80Gi','amd.com/gpu':2},'limits':{'memory':'110Gi','amd.com/gpu':2}},
   'securityContext':{'capabilities':{'add':['IPC_LOCK']}},
   'readinessProbe':{'httpGet':{'path':'/health','port':8000},'periodSeconds':10}}
p={'apiVersion':'v1','kind':'Pod','metadata':{'name':'flashnext-r9v-public','namespace':'llm'},'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,
 'nodeSelector':{'kubernetes.io/hostname':'iggy'},'tolerations':[{'key':k,'operator':'Exists','effect':'NoSchedule'} for k in ('node-role.kubernetes.io/control-plane','amd.com/gpu')],
 'securityContext':{'seccompProfile':{'type':'Unconfined'}},'containers':[c],'volumes':vols}}
(base/'r9v-public.json').write_text(json.dumps(p,indent=2)+'\n')
print('Preserved',len(env),'runtime environment values and',len(mounts),'mounts')
