import ast,json
from pathlib import Path
r=Path('/tmp/flashnext-competition');name='stew-q6-cache-layer-4k-host-map'
p=json.loads((r/'stew-q6-cache-layer-4k-loader.json').read_text());p['metadata']['name']='flashnext-'+name;c=p['spec']['containers'][0];next(e for e in c['env'] if e['name']=='MOE_EXPERT_CACHE_DEVMAP')['value']='0';(r/(name+'.json')).write_text(json.dumps(p,indent=2)+'\n')
(r/'q6-host-map-control-decision.json').write_text(json.dumps({'trigger':'Real repeated output in Q6 tensorhybrid, pureRCCL earlyEOS, and now memory-fit layer4K exactconcurrentreplay','source_control':'moe-expert-cache.cu lines379–400 explicitlydocuments DEVMAP0 eager per-op host routing readback and sync; also gates off devicepolicy and in-kernel slotlookup','change':'Only MOE_EXPERT_CACHE_DEVMAP1->0 compared to stew-q6-cache-layer-4k-loader','unchanged':'SameQ6/NVMe/CPU-expert split/two128Kslots/batch8192/ub4096/reserve1024','hypothesis':'Test whether device-side cache-remap path contributes; cause not established before results','qualification':'All matching C1/exactreplay/independentC2 outputs must be reviewed; API and memory checks required. Serial after currentretrycontroller.'},indent=2)+'\n')
(r/'run-q6-host-map.py').write_text('''"""Serial documented eager-host cache control after observed C2 failures."""
import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');print('HOST_MAP_WAITING_FOR_RETRY_CONTROLLER',flush=True)
while subprocess.run(['pgrep','-f',r'^/usr/bin/python3 -u /tmp/flashnext-competition/run-q6-layer-retry\\.py$'],capture_output=True).returncode==0:time.sleep(15)
name='stew-q6-cache-layer-4k-host-map';print('HOST_MAP_STARTING_SERIAL_SCREEN',flush=True)
with (r/(name+'-runner.log')).open('w') as f:
 p=subprocess.run(['/usr/bin/python3','-u',str(r/'run-profile.py'),str(r/(name+'.json')),'--llama','--smoke','--protocols','common,replay,c2'],stdout=f,stderr=subprocess.STDOUT)
print('HOST_MAP_SCREEN_FINISHED',p.returncode,flush=True);raise SystemExit(p.returncode)
''')
f=r/'finish-private-campaign.py';s=f.read_text().replace("'run-q6-layer-retry.py','run-profile.py'", "'run-q6-layer-retry.py','run-q6-host-map.py','run-profile.py'");ast.parse(s);f.write_text(s)
for fn,needle,repl in [
 ('copy-local-evidence.py',"'stew-q6-cache-layer-4k-fast-first']",f"'stew-q6-cache-layer-4k-fast-first','{name}']"),
 ('copy-local-evidence.py',"'q6-fast-first-decision.json']","'q6-fast-first-decision.json','q6-host-map-control-decision.json','q6-host-map-controller.log']"),
 ('render-q6-screens.py',"('Layer 4K fast card first','stew-q6-cache-layer-4k-fast-first')]",f"('Layer 4K fast card first','stew-q6-cache-layer-4k-fast-first'),('Layer 4K eager host remap','{name}')]"),
 ('render-memory-table.py',"('Q6 layer 4K fast card first','stew-q6-cache-layer-4k-fast-first')]",f"('Q6 layer 4K fast card first','stew-q6-cache-layer-4k-fast-first'),('Q6 layer 4K eager host remap','{name}')]"),
 ('render-performance-tables.py',"def read(name):",f"profiles += [('Q6 layer cache, 4K, eager host remap','{name}','{name}-pp','{name}-c2')]\ndef read(name):")]:
 f=r/fn;s=f.read_text();assert needle in s,fn;s=s.replace(needle,repl);ast.parse(s);f.write_text(s)
ast.parse((r/'run-q6-host-map.py').read_text());print('DOCUMENTED_HOST_MAP_CONTROL_PREPARED')
