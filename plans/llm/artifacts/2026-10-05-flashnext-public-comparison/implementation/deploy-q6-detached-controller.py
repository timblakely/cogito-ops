import hashlib,json,subprocess
from pathlib import Path
r=Path('/tmp/flashnext-competition');files=['profile-c2-replay-postpp.py','q6-detached-final-controller.py'];payload={f:(r/f).read_text() for f in files};code='''import hashlib,json,subprocess,sys
from pathlib import Path
r=Path('/workspace/flashnext-competition');files=json.load(sys.stdin)
for name,data in files.items():
 assert Path(name).name==name;(r/name).write_text(data)
existing=[]
for item in Path('/proc').glob('[0-9]*'):
 try:cmd=(item/'cmdline').read_bytes().split(bytes([0]))
 except (FileNotFoundError,PermissionError):continue
 if str(r/'q6-detached-final-controller.py').encode() in cmd:existing.append(int(item.name))
if existing:pid=existing[0]
else:
 log=(r/'results/q6-detached-final-controller.log').open('ab',buffering=0)
 p=subprocess.Popen(['python3','-u',str(r/'q6-detached-final-controller.py')],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);pid=p.pid
print(json.dumps({'pid':pid,'sha256':{name:hashlib.sha256((r/name).read_bytes()).hexdigest() for name in files}}))
'''
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','--request-timeout=15s','-n','llm'];result=subprocess.check_output(k+['exec','-i','flashnext-iggy-stage','--','python3','-c',code],input=json.dumps(payload).encode(),timeout=20);proof=json.loads(result);assert proof['sha256']=={f:hashlib.sha256((r/f).read_bytes()).hexdigest() for f in files};proof['note']='Same replay/prompt/protocol; guard repaired to exact real pp65536-2 label. Detached single-instance controller waits existingPPclient2668, doesnotrerunPP, thenreplay14/API3. HostVPNinterruptions no longer stop remainingprotocolchain.';(r/'q6-detached-controller-deployment-proof.json').write_text(json.dumps(proof,indent=2)+'\n');f=r/'postpp-replay-deployment-proof.json';old=json.loads(f.read_text());f.write_text(json.dumps({'previous':old,'updated_sha256':proof['sha256']['profile-c2-replay-postpp.py'],'updated_remote_path':'/workspace/flashnext-competition/profile-c2-replay-postpp.py','actual_remote_sha_matches':True,'change':'Onlypreconditioning guard lastlabel startswithpp65536-2- correctedto exactpp65536-2; replayrequests/promptnonces unchanged.'},indent=2)+'\n');print('DETACHED_CONTROLLER_DEPLOYED',proof)
