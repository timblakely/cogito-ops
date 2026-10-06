import ast
from pathlib import Path
f=Path('/tmp/flashnext-competition/run-profile.py');s=f.read_text();needle=" if profile.startswith('strata-'):\n";assert needle in s
s=s.replace(needle," if profile=='stew-q6-all-cache-layer-4k-headroom':\n  mem=subprocess.check_output(talos+['read','/proc/meminfo'],text=True)\n  available=int(next(line.split()[1] for line in mem.splitlines() if line.startswith('MemAvailable:')))*1024\n  if available < 112*2**30:\n   (root/(profile+'-memory-screen-decision.json')).write_text(json.dumps({'decision':'skip larger host backing: insufficient node MemAvailable for unchanged112GiB guard','available_bytes':available,'meminfo':mem},indent=2)+'\\n')\n   raise SystemExit('Insufficient available node RAM for larger Q6 backing; no Pod or measurement started')\n"+needle,1);ast.parse(s);f.write_text(s)
f=Path('/tmp/flashnext-competition/copy-local-evidence.py');s=f.read_text().replace("'q6-all-cache-fit-retry-decision.json']", "'q6-all-cache-fit-retry-decision.json','stew-q6-all-cache-layer-4k-headroom-memory-screen-decision.json']");ast.parse(s);f.write_text(s)
print('RETRY_REUSES_112GiB_AVAILABLE_RAM_GUARD')
