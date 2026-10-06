"""Keep original package intact; opt in to local RCCL symbol preference."""
import difflib,json
from pathlib import Path
r=Path('/tmp/flashnext-competition');orig=(r/'davetha-pynccl-wrapper-original.py').read_text();assert 'import os\n' not in orig;old='                lib = ctypes.CDLL(so_file)\n';assert orig.count(old)==1
new=orig.replace('import functools\n','import functools\nimport os\n').replace(old,'''                if os.getenv("FLASHNEXT_PYNCCL_DEEPBIND") == "1":
                    # Keep Torch's global RCCL symbols from handling this
                    # separately selected library's communicator objects.
                    lib = ctypes.CDLL(
                        so_file, mode=os.RTLD_NOW | os.RTLD_LOCAL | os.RTLD_DEEPBIND
                    )
                else:
                    lib = ctypes.CDLL(so_file)
''');compile(new,'deepbind-wrapper','exec');(r/'davetha-pynccl-wrapper-deepbind.py').write_text(new);(r/'davetha-pynccl-deepbind.patch').write_text(''.join(difflib.unified_diff(orig.splitlines(True),new.splitlines(True),fromfile='a/vllm/distributed/device_communicators/pynccl_wrapper.py',tofile='b/vllm/distributed/device_communicators/pynccl_wrapper.py')))
for before,after in [('davetha-probe-compat-debug','davetha-probe-compat-deepbind'),('davetha-public-compat-retry','davetha-public-compat-deepbind')]:
 j=json.loads((r/(before+'.json')).read_text());j['metadata']['name']='flashnext-'+after;c=j['spec']['containers'][0];c['env'].append({'name':'FLASHNEXT_PYNCCL_DEEPBIND','value':'1'});c['volumeMounts'].append({'name':'build','mountPath':'/app/vllm/vllm/distributed/device_communicators/pynccl_wrapper.py','subPath':'flashnext-competition/davetha-pynccl-wrapper-deepbind.py','readOnly':True});(r/(after+'.json')).write_text(json.dumps(j,indent=2)+'\n')
print('DEEPBIND_OVERLAY_PREPARED')
