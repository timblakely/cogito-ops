import hashlib,json,platform,sys
from pathlib import Path
root=Path('/workspace/flashnext-competition/R9V');sys.path.insert(0,str(root))
from tools.plan_experts import runtime_contract,plan
from tools.memory_seed import localize,verify_bundle
from tools.prepare_placement import _seed_source_contract
from tools.expert_budget import headroom_bytes
out=Path('/workspace/flashnext-competition/r9v-placement-tight');out.mkdir(exist_ok=True)
env=json.loads(Path('/workspace/flashnext-competition/r9v-profile-env.json').read_text())
for k,v in list(env.items()): env[k]=v.replace('/tmp/flashnext-competition/R9V',str(root))
package=root/'packages/models/qwen38-flash-next/ud-iq4-xs--mtp-blockfp8--mmproj-q8/package.json'
env.update(R9V_MODEL_DIR='/archive/llmkube/flashnext-iggy/r9v-iq4',R9V_PLE_PATH='/ngram/r9v/per_layer_token_embd.iq4_nl.bin',R9V_VISIBLE_DEVICES='1,0',R9V_EXPECTED_GPU_BDFS='0000:2f:00.0,0000:25:00.0',R9V_MODEL_PACKAGE_SHA256=hashlib.sha256(package.read_bytes()).hexdigest())
seedpath=Path(env['R9V_MEMORY_SEED_PATH']);seed=json.loads(seedpath.read_text());verify_bundle(seed,seedpath.parent)
source=Path(env['R9V_EXPERT_CATALOG_PATH']);original=Path(env['R9V_MODEL_DIR'])/'manifests/hot-manifest-q4-vision-128k-multiprompt-r1-lru16-neutral.json'
devices=[];external=[]
for bdf in env['R9V_EXPECTED_GPU_BDFS'].split(','):
 d=Path('/sys/bus/pci/devices')/bdf
 devices.append({'bdf':bdf,'total_bytes':int((d/'mem_info_vram_total').read_text())});external.append(int((d/'mem_info_vram_used').read_text()))
driver={'kernel':platform.release()}
for k in ('version','srcversion'):
 p=Path('/sys/module/amdgpu')/k;driver[k]=p.read_text().strip() if p.exists() else None
contract=runtime_contract(env,hashlib.sha256(source.read_bytes()).hexdigest(),devices,driver)
base=_seed_source_contract(seed,contract,contract['source_sha256'],original)
localized=localize(seed,base,external)
available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
runtime=json.loads(Path(env['R9V_RUNTIME_DESCRIPTOR']).read_text())
manifest,result=plan(json.loads(source.read_text()),localized,contract,headroom_bytes('1,1',2),available,allow_reference=True,runtime=runtime)
result.update(source_path=str(source),memory_seed_sha256=hashlib.sha256(seedpath.read_bytes()).hexdigest(),adapter='Talos CRI exact OCI index; fast GPU physical index 1 first; local qualification pending')
for n,obj in [('manifest.json',manifest),('plan.json',result),('contract.json',contract)]: (out/n).write_text(json.dumps(obj,indent=2)+'\n')
env.update(R9V_EXPERT_MANIFEST_PATH=str(out/'manifest.json'),R9V_PLACEMENT_PLAN=str(out/'plan.json'),R9V_CACHE_DIR='/workspace/flashnext-competition/r9v-cache',R9V_PREFLIGHT='0',R9V_CONTAINER_NAME='flashnext-r9v-public')
env['R9V_MAX_EFFECTIVE_EXPERTS_PER_RANK']=','.join(str(n+r['cache_physical_slots']) for n,r in zip(result['hot_counts'],result['expert_memory']))
(out/'env.json').write_text(json.dumps(env,indent=2)+'\n')
print(json.dumps(result,indent=2))
