import hashlib,json,tarfile,time
from pathlib import Path
root=Path('/workspace/flashnext-competition/strata');archive=Path('/archive/llmkube/flashnext-iggy/strata-mmq-runtime.tar.gz');proof=archive.parent/'build-provenance/strata-mmq/checksums.json';marker=root/'build/mmq-installed.json'
if marker.exists():print('STRATA_MMQ_ALREADY_INSTALLED');raise SystemExit(0)
for _ in range(120):
 if archive.exists() and proof.exists() and (proof.parent/'COMPLETE').exists():break
 time.sleep(5)
else:raise SystemExit('Off-node MMQ build not available')
# Producer publishes the archive only after a successful build; controller invokes after its completion.
work=root/'mmq-install';work.mkdir(exist_ok=True)
with tarfile.open(archive) as t:
 assert all(m.name.startswith('build/') for m in t);t.extractall(work,filter='data')
checks=json.loads(proof.read_text())
for name,expected in checks.items():
 with (work/name).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected,name
old=root/'build-before-mmq';assert not old.exists();(root/'build').rename(old);(work/'build').rename(root/'build');marker.write_text(json.dumps({'source_tag':'v0.1.39','STRATA_PREFILL_MMQ':True,'STRATA_PORTABLE':True,'checksums':checks},indent=2)+'\n');print('STRATA_MMQ_INSTALLED_VERIFIED',len(checks),flush=True)
