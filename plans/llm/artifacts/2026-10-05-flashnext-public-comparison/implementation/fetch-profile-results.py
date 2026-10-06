import argparse,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('profile');p.add_argument('protocols',nargs='+');a=p.parse_args();r=Path('/tmp/flashnext-competition/reviews');r.mkdir(exist_ok=True)
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','-n','llm']
for protocol in a.protocols:
 name=a.profile+'-'+protocol+'.json';data=subprocess.check_output(k+['exec','flashnext-iggy-stage','--','cat','/workspace/flashnext-competition/results/'+name]);j=json.loads(data);(r/name).write_bytes(data)
 if isinstance(j,list):
  print('FETCHED',name,json.dumps(j));assert all(t['passed'] for t in j);continue
 print('FETCHED',name,len(j.get('trials',[])))
 for t in j.get('trials',[]):print(t.get('label'),t.get('ok'),t.get('usage',{}).get('completion_tokens'),round(t.get('ttft_s',0),3),round(t.get('legacy_decode_tok_s') or 0,3))
 if protocol=='smoke':print(json.dumps(j))
