from pathlib import Path
r=Path('/tmp/flashnext-competition');name='stew-q6-all-cache-layer-4k-headroom'
for fn,needle,repl in [
 ('copy-local-evidence.py',"'stew-q6-cache-layer-4k-loader']",f"'stew-q6-cache-layer-4k-loader','{name}']"),
 ('copy-local-evidence.py',"'q6-layer-retry-controller.log']","'q6-layer-retry-controller.log','q6-all-cache-fit-retry-decision.json']"),
 ('render-q6-screens.py',"('Layer 4K microbatch retry','stew-q6-cache-layer-4k-loader')]",f"('Layer 4K microbatch retry','stew-q6-cache-layer-4k-loader'),('All-expert 4K / 2GiB reserve','{name}')]"),
 ('render-memory-table.py',"('Q6 layer 4K retry','stew-q6-cache-layer-4k-loader')]",f"('Q6 layer 4K retry','stew-q6-cache-layer-4k-loader'),('Q6 all-expert 4K / 2GiB reserve','{name}')]"),
 ('render-performance-tables.py',"def read(name):",f"profiles += [('Q6 all-expert cache, 4K / 2GiB reserve','{name}','{name}-pp','{name}-c2')]\ndef read(name):")]:
 f=r/fn;s=f.read_text();assert needle in s,(fn,needle);f.write_text(s.replace(needle,repl))
print('REPORT_MAPPINGS_UPDATED')
