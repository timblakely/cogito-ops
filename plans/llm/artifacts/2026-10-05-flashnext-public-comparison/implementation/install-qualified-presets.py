"""Install only manually qualified Q6 presets, then render inactive previews."""
import json,subprocess
from pathlib import Path
r=Path('/tmp/flashnext-competition');root=Path('/home/tim/git/cogito');manual=root/'kubernetes/apps/llm/llmkube/resources/manual';d=json.loads((r/'q6-qualification-decisions.json').read_text())['profiles'];selector=root/'scripts/llm/select_flashnext_iggy.py';active=root/'kubernetes/apps/llm/llmkube/resources/flashnext-iggy.yaml';before=active.read_bytes();s=selector.read_text();keys=[]
for key,profile,src,filename,qualification in [('q6-cache-c1','stew-q6-cache-layer-c1-qualified-full','q6-cache-c1-preset-preview.yaml','flashnext-iggy-q6-cache-c1.yaml','c1_qualified'),('q6-stew-c2','stew-q6-classic-r15-full-qualification','q6-stew-c2-preset-final-preview.yaml','flashnext-iggy-q6-stew-c2.yaml','c2_qualified')]:
 if not d.get(profile,{}).get(qualification):
  print('PRESET_NOT_INSTALLED_UNQUALIFIED',profile);continue
 assert d[profile]['screen_complete']
 (manual/filename).write_bytes((r/src).read_bytes())
 line=f'    "{key}": "{filename}",\n'
 if line not in s:s=s.replace('    "radiance":',line+'    "radiance":')
 keys.append(key)
selector.write_text(s)
for key in keys:subprocess.run(['/usr/bin/python3',str(selector),key,'--output',str(r/(key+'-selector-preview.yaml'))],check=True)
assert active.read_bytes()==before,'Installing suspended catalogue presets changed active workload'
print('QUALIFIED_PRESETS_INSTALLED',keys)
