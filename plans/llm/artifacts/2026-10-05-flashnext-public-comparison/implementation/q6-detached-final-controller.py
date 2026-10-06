"""Finish remaining protocols locally to the cluster; survive host VPN disconnects."""
import hashlib,json,subprocess,time,fcntl
from pathlib import Path
r=Path('/workspace/flashnext-competition');profile='stew-q6-classic-r15-full-qualification';endpoint='http://10.42.2.234:8080';state=r/'results/q6-detached-final-controller-state.json';expected_pid=2668

singleton=(r/'q6-detached-final-controller.lock').open('a')
try:fcntl.flock(singleton.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('Existing detached controller holds the singleton lock')

def write(phase,**extra):
 data={'phase':phase,'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'profile':profile,**extra};tmp=state.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(state);print(json.dumps(data),flush=True)
while True:
 try:cmd=(Path('/proc')/str(expected_pid)/'cmdline').read_bytes().split(b'\0')
 except FileNotFoundError:break
 if b'/workspace/flashnext-competition/flashnext_public_bench.py' not in cmd or b'pp' not in cmd:break
 pp=r/'results'/(profile+'-pp.json');n=len(json.loads(pp.read_text())['trials']) if pp.exists() else 0;write('waiting_existing_pp_client',pid=expected_pid,completed_trials=n);time.sleep(20)
pp=r/'results'/(profile+'-pp.json');data=json.loads(pp.read_text());assert len(data['trials'])==16 and all(t['ok'] for t in data['trials']);assert data['trials'][-1]['label']=='pp65536-2';assert all(t['tokens_by_tokenize']==t['usage']['prompt_tokens'] for t in data['trials']);write('postpp_replay_starting',preconditioning_sha256=hashlib.sha256(pp.read_bytes()).hexdigest())
with (r/'results'/(profile+'-detached-protocol.log')).open('w') as f:
 args=['python3',str(r/'profile-c2-replay-postpp.py'),'--endpoint',endpoint,'--profile',profile,'--protocol','postpp-replay','--output',str(r/'results'/(profile+'-postpp-replay.json')),'--thinking','default','--repetitions','3','--llama-cache-off'];rc=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT).returncode;f.flush();assert rc==0,rc
 write('api_starting',replay_returncode=rc)
 rc=subprocess.run(['python3',str(r/'profile-smoke.py'),'--endpoint',endpoint,'--output',str(r/'results'/(profile+'-smoke.json'))],stdout=f,stderr=subprocess.STDOUT).returncode;assert rc==0,rc
api=json.loads((r/'results'/(profile+'-smoke.json')).read_text());assert len(api)==3 and all(t['passed'] for t in api);write('protocols_complete_pending_manual_output_and_memory_review',pp_trials=16,replay_returncode=0,api_checks={t['case']:t['passed'] for t in api})
