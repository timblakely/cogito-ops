"""Validate direct CUDA peer access and data integrity on Iggy's two GPUs."""

import ctypes


for library in (
    "libcudart.so.13",
    "/usr/local/cuda-13.0/targets/x86_64-linux/lib/libcudart.so.13",
    "libcudart.so.12",
    "/usr/local/cuda-12.0/targets/x86_64-linux/lib/libcudart.so.12",
):
    try:
        cuda = ctypes.CDLL(library)
        break
    except OSError:
        continue
else:
    raise RuntimeError("CUDA runtime library is unavailable")


def bind(name, argtypes, restype=ctypes.c_int):
    function = getattr(cuda, name)
    function.argtypes = argtypes
    function.restype = restype
    return function


get_device_count = bind("cudaGetDeviceCount", [ctypes.POINTER(ctypes.c_int)])
can_access_peer = bind(
    "cudaDeviceCanAccessPeer",
    [ctypes.POINTER(ctypes.c_int), ctypes.c_int, ctypes.c_int],
)
set_device = bind("cudaSetDevice", [ctypes.c_int])
enable_peer = bind("cudaDeviceEnablePeerAccess", [ctypes.c_int, ctypes.c_uint])
malloc = bind("cudaMalloc", [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t])
free = bind("cudaFree", [ctypes.c_void_p])
memcpy = bind(
    "cudaMemcpy",
    [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int],
)
memcpy_peer = bind(
    "cudaMemcpyPeer",
    [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t],
)
get_error_string = bind("cudaGetErrorString", [ctypes.c_int], ctypes.c_char_p)


def check(status, operation):
    if status:
        message = get_error_string(status).decode()
        raise RuntimeError(f"{operation}: CUDA {status}: {message}")


count = ctypes.c_int()
check(get_device_count(ctypes.byref(count)), "cudaGetDeviceCount")
if count.value != 2:
    raise RuntimeError(f"expected two visible GPUs, found {count.value}")

for source, target in ((0, 1), (1, 0)):
    supported = ctypes.c_int()
    check(
        can_access_peer(ctypes.byref(supported), source, target),
        f"cudaDeviceCanAccessPeer({source}, {target})",
    )
    if not supported.value:
        raise RuntimeError(f"GPU {source} cannot access GPU {target}")

    check(set_device(source), f"cudaSetDevice({source})")
    status = enable_peer(target, 0)
    if status not in (0, 704):  # cudaErrorPeerAccessAlreadyEnabled
        check(status, f"cudaDeviceEnablePeerAccess({target})")

    size = 8 * 1024 * 1024
    pattern = bytes((i + source) % 256 for i in range(256)) * (size // 256)
    input_buffer = ctypes.create_string_buffer(pattern)
    output_buffer = ctypes.create_string_buffer(size)
    source_ptr = ctypes.c_void_p()
    target_ptr = ctypes.c_void_p()

    try:
        check(malloc(ctypes.byref(source_ptr), size), "cudaMalloc(source)")
        check(
            memcpy(source_ptr, input_buffer, size, 1),
            "cudaMemcpy(host to source)",
        )
        check(set_device(target), f"cudaSetDevice({target})")
        check(malloc(ctypes.byref(target_ptr), size), "cudaMalloc(target)")
        check(
            memcpy_peer(target_ptr, target, source_ptr, source, size),
            f"cudaMemcpyPeer({source} to {target})",
        )
        check(
            memcpy(output_buffer, target_ptr, size, 2),
            "cudaMemcpy(target to host)",
        )
        if output_buffer.raw != pattern:
            raise RuntimeError(f"GPU {source} to {target} corrupted data")
        print(f"GPU {source} to {target}: peer access and 8 MiB copy verified")
    finally:
        if target_ptr.value:
            check(set_device(target), f"cudaSetDevice({target})")
            check(free(target_ptr), "cudaFree(target)")
        if source_ptr.value:
            check(set_device(source), f"cudaSetDevice({source})")
            check(free(source_ptr), "cudaFree(source)")
