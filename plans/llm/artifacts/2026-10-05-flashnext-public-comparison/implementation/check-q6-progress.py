"""Display compact local progress for the serial Q6 campaign."""
import json
from pathlib import Path
r=Path('/tmp/flashnext-competition');controller=r/'q6-final-controller.log'
if controller.exists():print('CONTROLLER',controller.read_text().splitlines()[-4:])
for f in sorted(r.glob('stew-q6*-campaign.log'),key=lambda p:p.stat().st_mtime,reverse=True)[:1]:
 rows=[]
 for line in f.read_text().splitlines():
  try:j=json.loads(line)
  except ValueError:continue
  if isinstance(j,dict) and j.get('label'):rows.append(j)
 print('PROFILE',f.name,'completed_matching_requests',len(rows))
 for t in rows[-2:]:print({k:t.get(k) for k in ('label','ok','usage','ttft_s','wall_s','legacy_decode_tok_s')})
 for line in f.read_text().splitlines()[-3:]:
  if line.startswith(('INITIAL_','REPLAY','Traceback','Error')):print(line)
