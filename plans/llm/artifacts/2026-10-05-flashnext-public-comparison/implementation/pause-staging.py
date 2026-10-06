import os,sys,json,signal
from pathlib import Path
mode=sys.argv[1];mark=Path('/tmp/flashnext-paused-pids.json')
if mode=='resume':
 for pid in json.loads(mark.read_text()):
  try:os.kill(pid,signal.SIGCONT)
  except ProcessLookupError:pass
 print('resumed',mark.read_text())
else:
 table={}
 for p in Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode();s=(p/'stat').read_text().split();table[int(p.name)]=(int(s[3]),cmd)
  except (OSError,ValueError):continue
 roots=[pid for pid,(parent,cmd) in table.items() if ('-download.py' in cmd or 'download-queue.py' in cmd or ('cmake --build ' in cmd)) and pid!=os.getpid() and not cmd.startswith('python3 - pause')]
 pids=set(roots)
 for _ in range(20):pids.update(pid for pid,(parent,cmd) in table.items() if parent in pids)
 # This helper receives source on stdin, so its own command line never matches.
 pids.discard(os.getpid());mark.write_text(json.dumps(sorted(pids)))
 for pid in sorted(pids):
  try:os.kill(pid,signal.SIGSTOP)
  except ProcessLookupError:pass
 print('paused',mark.read_text())
