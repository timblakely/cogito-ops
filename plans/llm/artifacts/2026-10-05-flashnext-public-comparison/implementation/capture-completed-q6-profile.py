"""Capture final memory/logs and resume owned auxiliaries without repeating requests."""
import json,subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');profile='stew-q6-classic-r15-full-qualification';name='flashnext-'+profile;k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','--request-timeout=15s','-n','llm']
def capture(args,**kwargs):return subprocess.check_output(k+args,timeout=25,**kwargs)
state=json.loads(capture(['exec','flashnext-iggy-stage','--','cat','/workspace/flashnext-competition/results/q6-detached-final-controller-state.json']));assert state['phase']=='protocols_complete_pending_manual_output_and_memory_review';assert all(state['api_checks'].values())
pod=json.loads(capture(['get','pod',name,'-o','json']));assert pod['status']['containerStatuses'][0]['ready'];assert pod['status']['containerStatuses'][0]['restartCount']==0;assert pod['metadata']['uid']=='318d02fe-b684-43a8-b57f-d0d7523f1019';(r/(profile+'-final-pod.json')).write_text(json.dumps(pod,indent=2)+'\n')
(r/(profile+'-runtime.log')).write_bytes(capture(['logs',name]));memory=capture(['exec','-i',name,'--','python3','-'],input=(r/'runtime-memory.py').read_bytes());json.loads(memory);(r/(profile+'-memory.json')).write_bytes(memory)
for aux in ('flashnext-iggy-stage','flashnext-r9v-stage','flashnext-davetha-stage','flashnext-public-download'):
 output=capture(['exec','-i',aux,'--','python3','-','resume'],input=(r/'pause-staging.py').read_bytes());print('OWNED_AUX_RESUMED',aux,output.decode().strip())
(r/'q6-detached-final-capture-proof.json').write_text(json.dumps({'detached_state':state,'pod_uid':pod['metadata']['uid'],'pod_ready':True,'restart_count':0,'final_memory_and_runtime_logs_retained':True,'owned_auxiliaries_resumed':True},indent=2)+'\n');print('Q6_FINAL_CAPTURE_COMPLETE')
