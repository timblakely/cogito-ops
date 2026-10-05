#include "arg.h"
#include "common.h"
#include "fit.h"
#include "ggml-backend.h"
#include <cstdio>
int main(int argc, char **argv) {
 common_init();
 ggml_backend_load_all();
 common_params params;
 if (!common_params_parse(argc,argv,params,LLAMA_EXAMPLE_SERVER)) return 1;
 llama_backend_init();
 auto mp=common_model_params_to_llama(params);
 auto cp=common_context_params_to_llama(params);
 std::vector<ggml_backend_dev_t> devs;
 uint32_t ngl,ctx,experts;
 auto rows=common_get_device_memory_data(params.model.path.c_str(),&mp,&cp,devs,ngl,ctx,experts,GGML_LOG_LEVEL_WARN);
 std::puts("[");
 for (size_t i=0;i<rows.size();i++) {
  const auto &r=rows[i];
  std::printf("{\"device\":\"%s\",\"total\":%lld,\"free_now\":%lld,\"weights\":%zu,\"context\":%zu,\"compute\":%zu}%s\n",i<devs.size()?ggml_backend_dev_name(devs[i]):"host",(long long)r.total,(long long)r.free,r.model,r.context,r.compute,i+1==rows.size()?"":",");
 }
 std::puts("]");
 llama_backend_free();
}
