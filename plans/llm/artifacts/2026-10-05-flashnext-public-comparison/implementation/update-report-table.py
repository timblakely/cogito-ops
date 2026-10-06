import subprocess
from pathlib import Path
r=Path('/tmp/flashnext-competition');root=Path('/home/tim/git/cogito');subprocess.run(['/usr/bin/python3',str(r/'render-performance-tables.py'),str(root/'plans/llm/artifacts/2026-10-05-flashnext-public-comparison/results'),'--output',str(r/'comparison-table.md')],check=True)
p=root/'plans/llm/flashnext-public-comparison-2026-10-05.md';s=p.read_text();start='<!-- completed-comparison:start -->';end='<!-- completed-comparison:end -->';left,rest=s.split(start,1);_,right=rest.split(end,1);p.write_text(left+start+'\n'+(r/'comparison-table.md').read_text()+end+right)

subprocess.run(['/usr/bin/python3',str(r/'render-memory-table.py'),str(root/'plans/llm/artifacts/2026-10-05-flashnext-public-comparison/provenance'),'--output',str(r/'memory-table.md')],check=True)
s=p.read_text();start='<!-- memory-comparison:start -->';end='<!-- memory-comparison:end -->';left,rest=s.split(start,1);_,right=rest.split(end,1);p.write_text(left+start+'\n'+(r/'memory-table.md').read_text()+end+right)
