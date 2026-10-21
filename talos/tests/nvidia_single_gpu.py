"""Check one allocated GPU using CUDA's driver API; no toolkit or PyTorch needed."""

import argparse
import ctypes as c
import json
import time
import uuid


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--seconds", type=float, default=0)
options = parser.parse_args()
cuda = c.CDLL("libcuda.so.1")


def bind(name, args):
    function = getattr(cuda, name)
    function.argtypes = args
    function.restype = c.c_int
    return function


error_string = bind("cuGetErrorString", [c.c_int, c.POINTER(c.c_char_p)])


def check(status):
    if status:
        message = c.c_char_p()
        error_string(status, c.byref(message))
        raise RuntimeError(f"CUDA {status}: {message.value!r}")


init = bind("cuInit", [c.c_uint])
device_count = bind("cuDeviceGetCount", [c.POINTER(c.c_int)])
device_name = bind("cuDeviceGetName", [c.c_void_p, c.c_int, c.c_int])
device_uuid = bind("cuDeviceGetUuid", [c.c_void_p, c.c_int])
total_memory = bind("cuDeviceTotalMem_v2", [c.POINTER(c.c_size_t), c.c_int])
retain = bind("cuDevicePrimaryCtxRetain", [c.POINTER(c.c_void_p), c.c_int])
release = bind("cuDevicePrimaryCtxRelease_v2", [c.c_int])
set_current = bind("cuCtxSetCurrent", [c.c_void_p])
allocate = bind("cuMemAlloc_v2", [c.POINTER(c.c_uint64), c.c_size_t])
free = bind("cuMemFree_v2", [c.c_uint64])
to_device = bind("cuMemcpyHtoD_v2", [c.c_uint64, c.c_void_p, c.c_size_t])
to_host = bind("cuMemcpyDtoH_v2", [c.c_void_p, c.c_uint64, c.c_size_t])
load = bind("cuModuleLoadData", [c.POINTER(c.c_void_p), c.c_void_p])
unload = bind("cuModuleUnload", [c.c_void_p])
get_function = bind("cuModuleGetFunction", [c.POINTER(c.c_void_p), c.c_void_p, c.c_char_p])
launch = bind("cuLaunchKernel", [c.c_void_p] + [c.c_uint] * 7 + [c.c_void_p] * 3)

check(init(0))
count = c.c_int()
check(device_count(c.byref(count)))
if count.value != 1:
    raise RuntimeError(f"Expected one allocated GPU, found {count.value}")
name = c.create_string_buffer(256)
identifier = (c.c_ubyte * 16)()
memory = c.c_size_t()
check(device_name(name, len(name), 0))
check(device_uuid(identifier, 0))
check(total_memory(c.byref(memory), 0))
print(json.dumps({"gpu": name.value.decode(), "uuid": "GPU-" + str(uuid.UUID(bytes=bytes(identifier))),
                  "vram_bytes": memory.value, "visible_devices": count.value}), flush=True)

ptx = c.create_string_buffer(b"""
.version 7.1
.target sm_86
.address_size 64
.visible .entry increment(.param .u64 data, .param .u32 n) {
    .reg .pred %p;
    .reg .b32 %r<6>;
    .reg .b64 %rd<3>;
    ld.param.u64 %rd0, [data];
    ld.param.u32 %r0, [n];
    mov.u32 %r1, %ctaid.x;
    mov.u32 %r2, %ntid.x;
    mov.u32 %r3, %tid.x;
    mad.lo.u32 %r4, %r1, %r2, %r3;
    setp.ge.u32 %p, %r4, %r0;
    @%p bra DONE;
    mul.wide.u32 %rd1, %r4, 4;
    add.s64 %rd2, %rd0, %rd1;
    ld.global.u32 %r5, [%rd2];
    add.u32 %r5, %r5, 1;
    st.global.u32 [%rd2], %r5;
DONE:
    ret;
}
""")
context, module, function = c.c_void_p(), c.c_void_p(), c.c_void_p()
pointer, length = c.c_uint64(), c.c_uint(1024 * 1024)
host = (c.c_uint32 * length.value)()
check(retain(c.byref(context), 0))
try:
    check(set_current(context))
    check(allocate(c.byref(pointer), c.sizeof(host)))
    check(to_device(pointer, host, c.sizeof(host)))
    check(load(c.byref(module), ptx))
    check(get_function(c.byref(function), module, b"increment"))
    arguments = (c.c_void_p * 2)(c.addressof(pointer), c.addressof(length))
    end = time.monotonic() + options.seconds
    iterations = 0
    while True:
        check(launch(function, length.value // 256, 1, 1, 256, 1, 1, 0, None, arguments, None))
        check(to_host(host, pointer, c.sizeof(host)))
        iterations += 1
        if time.monotonic() >= end:
            break
    if any(value != iterations for value in host):
        raise RuntimeError("CUDA kernel or device-to-host data integrity check failed")
    print(json.dumps({"result": "passed", "elements": length.value, "iterations": iterations}), flush=True)
finally:
    if module:
        check(unload(module))
    if pointer.value:
        check(free(pointer))
    check(release(0))
