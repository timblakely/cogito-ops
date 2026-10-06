import time,runpy
from pathlib import Path
root=Path('/workspace/flashnext-competition');log=root/'r9v-download.log'
while 'All Q6 shards verified' not in log.read_text():time.sleep(5)
print('R9V package finished; staging published IQ3 and MXFP4 assets',flush=True)
runpy.run_path(str(root/'iq3-download.py'),run_name='__main__')
runpy.run_path(str(root/'davetha-download.py'),run_name='__main__')
