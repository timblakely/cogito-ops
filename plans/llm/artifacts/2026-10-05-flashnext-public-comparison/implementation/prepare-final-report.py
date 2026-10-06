"""Prepare a coherent final report; unresolved fields remain in /tmp only."""
import re
from pathlib import Path
r=Path('/tmp/flashnext-competition');source=Path('/home/tim/git/cogito/plans/llm/flashnext-public-comparison-2026-10-05.md').read_text();parts=re.split(r'^## ',source,flags=re.M);sections={x.split('\n',1)[0]:x.split('\n',1)[1].strip() for x in parts[1:]}
def section(name):return '## '+name+'\n\n'+sections[name]+'\n\n'
s='''# Flash Next public-runtime comparison on Iggy

The exact workstation Atomic Q4 is fastest on Iggy with the uncached Stew r15 placement: warmed short generation is 48.67 tokens/s and median 40K generation is 42.51, about 49% and 56% above the earlier workstation baseline. __FINAL_PUBLIC_WINNERS__

__FINAL_Q6_RECOMMENDATION__

All active n-gram tables stay on local NVMe. The same Atomic table is retained for the workstation control; alternative quants have different table precision and conventional weights. This report measures performance and bounded correctness/API checks, not equivalent quality against BF16. The original [Iggy/workstation report](flashnext-iggy-benchmark-2026-10-05.md) remains the historical baseline. [Retained evidence](artifacts/2026-10-05-flashnext-public-comparison/index.json) includes completed trials, failed starts and prepared alternatives; [coverage](artifacts/2026-10-05-flashnext-public-comparison/campaign-coverage.json) distinguishes them.

'''
s+=section('Completed comparison at a glance')
s+=section('Public raw-generation comparison')
s+=section('Comparable measurements')
s+=section('Quant and n-gram differences')
s+=section('Results completed so far').replace('## Results completed so far','## Exact Atomic Q4 against the workstation')
s+=section('Native Radiance gap')
s+=section('R9V, original IQ4_XS and CED off')
s+=section('Stew correctness qualification')
s+='## Higher fidelity Q6 qualification\n\n__FINAL_Q6_RESULTS__\n\n'
s+='## Public LRU qualification\n\n__FINAL_LRU_RESULTS__\n\n'
for name in ['Shali r30 on one GPU','John IQ3 plain','John IQ3 MTP, balanced retry','Dual-card Stew r15 MTP control','Strata single-card base, completed','Strata dual-card base, completed','Strata dual-card WMMA, completed']:
 block=section(name).replace('The separate dual base run will distinguish those configurations more closely; PCIe topology alone is not established as the cause of the generation difference.','The completed dual base run narrows that comparison; PCIe topology alone is not established as the cause of the generation difference.')
 s+=block
s+='## Hardware, memory and compatibility\n\nIggy retains Talos 1.13.5 and kernel 6.18.36, with a Ryzen 9 3900X, 128 GB system RAM and two 32 GB R9700s. Runtime images and staged SDKs supply the required user-space changes. The table records physical VRAM and cgroup RAM after each suite; the failed all-expert profiles are explicitly captured after their long-request allocation failures, so a released compute buffer can reduce the final usage on one card.\n\n__FINAL_MEMORY_TABLE__\n\n'
s+=section('Collective compatibility on Iggy')
s+='__FINAL_LRU_COMPATIBILITY__\n\n'
s+=section('Public sources and reproduction boundaries').split('\n\nThe newer-glibc LRU retry',1)[0]+'\n\n'
s=s.replace("The prepared profiles cover original R9V IQ4_XS with CED off, Stew caching on matching Q4 and Q6, Shali's single-card plain/MTP recipe, John's original IQ3_XXS quant, Strata single/dual GPU, and the public ROCm 10 LRU configuration. Their measurements, memory observations and production choice will be added after qualification.", "The measured profiles cover original R9V IQ4_XS with CED off, Stew caching on matching Q4 and Q6, Shali's single-card plain/MTP recipe, John's original IQ3_XXS quant, Strata single/dual GPU, and the public ROCm 10 LRU configuration. The tables and retained coverage distinguish completed suites, rejected screens and prepared alternatives.")
s+='''## Reproduction and production outcome

__FINAL_REPRODUCTION_AND_DEPLOYMENT__
'''
(r/'final-report-template.md').write_text(s);print('FINAL_REPORT_TEMPLATE_PREPARED',len(s))
