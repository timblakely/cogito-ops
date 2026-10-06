import subprocess,time
from pathlib import Path
r=Path('/tmp/flashnext-competition');k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','-n','llm'];t=['/home/tim/.local/share/mise/installs/talosctl/1.13.5/talosctl','--talosconfig','/home/tim/git/cogito/talosconfig','-n','192.168.42.13']
while subprocess.run(['pgrep','-f','^/usr/bin/python3 -u /tmp/flashnext-competition/run-final-public-queue.py$'],capture_output=True).returncode==0:time.sleep(10)
for _ in range(40):
 used=[int(subprocess.check_output(t+['read',f'/sys/class/drm/card{i}/device/mem_info_vram_used'])) for i in (0,1)]
 if max(used)<256*1024*1024:break
 time.sleep(3)
else:raise SystemExit('VRAM did not release before compatibility preparation')
subprocess.run(k+['exec','-i','flashnext-davetha-stage','--','python3','-'],input=(r/'prepare-davetha-compat.py').read_bytes(),check=True)
subprocess.run(k+['apply','-f',str(r/'davetha-compat-stage.json')],check=True)
subprocess.run(k+['wait','--for=condition=Ready','pod/flashnext-davetha-compat-stage','--timeout=180s'],check=True)
code=(r/'davetha-cpu-abi-probe.py').read_text();code=code.replace("shutil.copytree('/workspace/flashnext-competition/davetha-overlays/vllm','/app/vllm/vllm',dirs_exist_ok=True)","")
code+='\nfrom vllm.distributed.device_communicators.pynccl_wrapper import NCCLLibrary\nprint("RCCL_CPU_ABI",NCCLLibrary("/workspace/flashnext-competition/librccl-nohostcall-2.27.7-multiarch.so").ncclGetVersion(),flush=True)\n'
with (r/'davetha-compat-cpu-abi.log').open('wb') as f:subprocess.run(k+['exec','-i','flashnext-davetha-compat-stage','--','python3','-'],input=code.encode(),stdout=f,stderr=subprocess.STDOUT,check=True)
(r/'compat-preparation-complete').write_text('CPU ABI PASS; GPU qualification still required\n');print('COMPAT_PREPARATION_CPU_PASS',flush=True)
cmd=subprocess.check_output(['ps','-p','2040424','-o','args='],text=True).strip();assert cmd=='/usr/bin/python3 -u /tmp/flashnext-competition/run-control-queue.py',cmd
subprocess.run(['kill','-CONT','2040424'],check=True);print('CONTROL_QUEUE_RESUMED',flush=True)
