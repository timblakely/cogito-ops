import subprocess
from pathlib import Path

root=Path('/ngram/davetha-sdk')
root.mkdir(exist_ok=True)
subprocess.run(['python3','-m','pip','install','--no-cache-dir','--target',str(root),
                '--extra-index-url','https://stable.repo.amd.com/rocm/whl-next',
                '--report','/workspace/flashnext-competition/davetha-sdk-pip-report.json',
                'torch[device-gfx1201]==2.11.0+rocm10.0.0',
                'torchvision==0.26.0+rocm10.0.0','torchaudio==2.11.0+rocm10.0.0',
                'numpy==2.3.5','setuptools==79.0.1'],check=True)
print('DAVETHA_SDK_COMPLETE',flush=True)
