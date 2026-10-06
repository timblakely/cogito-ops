"""Confirm runtime device order without allocating benchmark data."""
import ctypes,json,os
h=ctypes.CDLL('libamdhip64.so');n=ctypes.c_int();assert h.hipGetDeviceCount(ctypes.byref(n))==0
records=[]
for i in range(n.value):
 b=ctypes.create_string_buffer(64);assert h.hipDeviceGetPCIBusId(b,64,i)==0;records.append({'runtime_index':i,'bdf':b.value.decode()})
assert [x['bdf'].lower().removeprefix('0000:') for x in records]==['2f:00.0','25:00.0'],records
print(json.dumps({'ROCR_VISIBLE_DEVICES':os.environ.get('ROCR_VISIBLE_DEVICES'),'HIP_VISIBLE_DEVICES':os.environ.get('HIP_VISIBLE_DEVICES'),'devices':records,'check':'CPU-connected GPU first, chipset GPU second; no model/benchmark allocation'},indent=2))
