"""Validate retained evidence, links and source without mirroring benchmark behavior."""
import argparse,ast,json,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--report',type=Path);a=p.parse_args();root=Path('/home/tim/git/cogito');data=root/'plans/llm/artifacts/2026-10-05-flashnext-public-comparison';counts={'json':0,'python':0}
for f in data.rglob('*.json'):json.loads(f.read_text());counts['json']+=1
for f in data.rglob('*.py'):ast.parse(f.read_text(),filename=str(f));counts['python']+=1
for f in (root/'scripts/llm/flashnext_public_bench.py',root/'scripts/llm/select_flashnext_iggy.py'):ast.parse(f.read_text(),filename=str(f));counts['python']+=1
if a.report:
 s=a.report.read_text();assert not re.findall(r'__[A-Z][A-Z0-9_]+__',s),'Unresolved report fields';assert 'campaign is still running' not in s
 missing=[]
 for href in re.findall(r'\]\(([^)]+)\)',s):
  if re.match(r'https?://',href):continue
  target=(a.report.parent/href.split('#')[0]);
  if not target.exists():missing.append(href)
 assert not missing,missing
secret_patterns=[r'github_pat_[A-Za-z0-9_]{30,}',r'gh[pousr]_[A-Za-z0-9]{30,}',r'sk-[A-Za-z0-9_-]{30,}']
for f in data.rglob('*'):
 if f.is_file():
  content=f.read_text(errors='replace')
  assert not any(re.search(pattern,content) for pattern in secret_patterns),'Credential-like token found in '+str(f)
counts['credential_pattern_scan']=True
counts['report_links_checked']=bool(a.report)
print('FINAL_ARTIFACT_VALIDATION',counts)
