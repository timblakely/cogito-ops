"""One cold-prefix full-context request using the pinned PP corpus."""
import argparse,json,time
from pathlib import Path
from flashnext_public_bench import fit,trial
p=argparse.ArgumentParser();p.add_argument('--endpoint',required=True);p.add_argument('--profile',required=True);p.add_argument('--tokens',type=int,default=131000);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
model='qwen3.8-flash-next';corpus=Path('/workspace/flashnext-competition/aider-chat-history.md').read_text();prompt,n=fit(a.endpoint,model,f'context qualification {time.time_ns()}\n',corpus,a.tokens)
record=trial(a.endpoint,{'model':model,'prompt':prompt,'temperature':0,'seed':7,'max_tokens':16},'max-context-'+str(n));record['tokens_by_tokenize']=n
j={'profile':a.profile,'protocol':'context-qualification','trials':[record]};a.output.write_text(json.dumps(j,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k not in ('text','reasoning_text','before','after')}));raise SystemExit(0 if record.get('ok') else 1)
