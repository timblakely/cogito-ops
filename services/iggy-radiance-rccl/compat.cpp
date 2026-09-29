#include <cstdio>
#include <string>
#include <unordered_map>

// Radiance 0.9.3's PyTorch 2.11 links seven symbols that ROCm 7.1.1 RCCL
// does not export. The collective path does not use the six APIs below.
// Make an unexpected call fail visibly instead of silently pretending it ran.
struct ncclComm;

__attribute__((visibility("default")))
int ncclCommDump(ncclComm*, std::unordered_map<std::string, std::string>&) {
  return 0;  // Debug-only state dump; unused during inference.
}

static int unsupported(const char* symbol) {
  std::fprintf(stderr, "Iggy RCCL compatibility stub called: %s\n", symbol);
  return 5;  // ncclInvalidUsage
}

extern "C" {
int ncclDevCommCreate(...) { return unsupported("ncclDevCommCreate"); }
int ncclDevCommDestroy(...) { return unsupported("ncclDevCommDestroy"); }
int ncclGetLsaMultimemDevicePointer(...) {
  return unsupported("ncclGetLsaMultimemDevicePointer");
}
int ncclPutSignal(...) { return unsupported("ncclPutSignal"); }
int ncclSignal(...) { return unsupported("ncclSignal"); }
int ncclWaitSignal(...) { return unsupported("ncclWaitSignal"); }
}
