import argparse,asyncio,json
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from vllm import envs
from vllm.entrypoints.launchers.api_server.routers import register_api_routers
assert envs.VLLM_SERVER_DEV_MODE
app=FastAPI();args=argparse.Namespace();app.state.args=args;register_api_routers(args,app,('generate',))
assert any(getattr(r,'path',None)=='/reset_prefix_cache' for r in app.routes)
class Engine:
 async def reset_prefix_cache(self,*args):return True
app.state.engine_client=Engine()
r=TestClient(app).post('/reset_prefix_cache',json={})
assert r.status_code==200 and r.json()=={'success':True},(r.status_code,r.text)
proof={'environment':'VLLM_SERVER_DEV_MODE=1','original_router_file':register_api_routers.__code__.co_filename,'reset_prefix_cache_http_status':r.status_code,'response':r.json(),'qualification':'Actual published API-router registration, HTTP route and success response tested with mocked engine cache reset; full engine reset is verified separately during benchmarking.'}
Path('/workspace/flashnext-competition/results/davetha-cache-route-probe.json').write_text(json.dumps(proof,indent=2)+'\n');print('PUBLISHED_CACHE_RESET_ROUTE_PASS',proof,flush=True)
