"""Restore the scoped NFS setting and delete only explicitly owned staging Pods."""
import argparse,json,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args();r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','-n','llm']
owned=['flashnext-iggy-stage','flashnext-r9v-stage','flashnext-davetha-stage','flashnext-davetha-compat-stage','flashnext-public-download','flashnext-public-build','flashnext-shali-sdk10-link-probe','flashnext-nfs-readahead','flashnext-nfs-readahead-restore']
if not a.execute:print('Explicit cleanup plan:',owned);raise SystemExit(0)
for controller in ('run-public-retries.py','run-davetha-deepbind.py','run-davetha-local.py','run-q6-final.py','run-q6-layer-retry.py','run-q6-host-map.py','run-q6-qualified.py','run-profile.py'):
 probe=subprocess.run(['pgrep','-f',r'^/usr/bin/python3 -u /tmp/flashnext-competition/'+controller.replace('.',r'\.')+r'( |$)'],capture_output=True)
 assert probe.returncode!=0,'benchmark controller remains active: '+controller
subprocess.run(k+['apply','-f',str(r/'nfs-readahead-restore.json')],check=True)
for _ in range(30):
 pod=json.loads(subprocess.check_output(k+['get','pod','flashnext-nfs-readahead-restore','-o','json']))
 if pod['status']['phase'] in ('Succeeded','Failed'):break
 time.sleep(2)
log=subprocess.check_output(k+['logs','flashnext-nfs-readahead-restore'],text=True);(r/'nfs-readahead-restored.log').write_text(log);assert pod['status']['phase']=='Succeeded',log;proof=json.loads(log);assert proof['after_kib']==128;print('NFS_RESTORED',proof,flush=True)
subprocess.run(k+['delete','pod',*owned,'--ignore-not-found=true','--wait=true'],check=True)
print('PRIVATE_STAGES_REMOVED; reconciliation holds still require restoration after publication',flush=True)
