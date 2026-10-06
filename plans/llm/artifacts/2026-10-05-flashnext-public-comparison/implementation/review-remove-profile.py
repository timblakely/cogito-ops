import argparse,json,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('profile');p.add_argument('--qualified',action='store_true');p.add_argument('--marker',action='store_true');a=p.parse_args();r=Path('/tmp/flashnext-competition');name='flashnext-'+a.profile
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','-n','llm']
subprocess.run(k+['exec',name,'--','python3','-c','import os,signal; os.kill(1,signal.SIGTERM)'],capture_output=True)
for _ in range(25):
 j=json.loads(subprocess.check_output(k+['get','pod',name,'-o','json']))
 if any(x.get('state',{}).get('terminated') for x in j['status'].get('containerStatuses',[])):break
 time.sleep(1)
with (r/(a.profile+'-shutdown.log')).open('wb') as f:subprocess.run(k+['logs',name],stdout=f,check=True)
subprocess.run(k+['delete','pod',name,'--wait=true'],check=True)
if a.marker:(r/(a.profile+'-reviewed-and-removed.json')).write_text(json.dumps({'profile':a.profile,'pod_removed':True,'qualified':a.qualified},indent=2)+'\n')
