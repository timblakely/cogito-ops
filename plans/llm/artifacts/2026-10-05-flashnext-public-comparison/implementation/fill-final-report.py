"""Fill the final report only when every result and restoration field is ready."""
import argparse,json,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--preview',action='store_true');p.add_argument('--reuse-template',action='store_true',help='Reuse the prepared template when amending a completed report');a=p.parse_args();r=Path('/tmp/flashnext-competition')
if not a.reuse_template:subprocess.run(['/usr/bin/python3',str(r/'prepare-final-report.py')],check=True)
s=(r/'final-report-template.md').read_text();fields=json.loads((r/'final-report-fields.json').read_text())
for key,file in [('__FINAL_LRU_RESULTS__','lru-final-results.md'),('__FINAL_LRU_COMPATIBILITY__','lru-compatibility.md'),('__FINAL_MEMORY_TABLE__','memory-table.md')]:fields[key]=(r/file).read_text().strip()
for key,value in fields.items():assert key.startswith('__FINAL_') and key.endswith('__');s=s.replace(key,value)
s=s.replace('The exact workstation Atomic Q4 is fastest on Iggy with the uncached Stew r15 placement:','For the exact workstation Atomic Q4, uncached Stew r15 gives the best measured common-request latency:')
s=s.replace('The prospective cache profiles set','The cache profiles set')
s=s.replace('short columns average repetitions two and three','short columns average repetitions two and three')
remaining=re.findall(r'__FINAL_[A-Z0-9_]+__',s)
if a.preview:
 (r/'final-report-preview.md').write_text(s);print('PREVIEW_UNRESOLVED',remaining)
else:
 assert not remaining,remaining
 assert 'The campaign is still running' not in s
 Path('/home/tim/git/cogito/plans/llm/flashnext-public-comparison-2026-10-05.md').write_text(s);print('FINAL_REPORT_WRITTEN',len(s))
