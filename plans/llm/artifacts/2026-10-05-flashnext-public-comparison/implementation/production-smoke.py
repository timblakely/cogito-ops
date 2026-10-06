"""Check the deployed alias with the Hermes key; retain responses without credentials."""
import base64,json,subprocess
from pathlib import Path
k=['/home/tim/.local/share/mise/installs/kubectl/1.37.1/kubectl','--kubeconfig','/home/tim/git/cogito/kubeconfig','--server','https://192.168.42.13:6443','-n','llm']
s=json.loads(subprocess.check_output(k+['get','secret','litellm-key-hermes','-o','json']))
key=base64.b64decode(s['data']['api-key']).decode()
code=r'''import json,sys,urllib.request,urllib.error
key=sys.stdin.read()
tool={"type":"function","function":{"name":"get_weather","description":"Get weather in a city","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}
items=[('arithmetic',{"messages":[{"role":"user","content":"What is 17 * 19? Answer with just the integer."}]}),('json_object',{"messages":[{"role":"user","content":"Return a JSON object with result equal to 17 * 19. Only JSON."}],"response_format":{"type":"json_object"}}),('schema',{"messages":[{"role":"user","content":"Return status IGGY_SCHEMA_OK."}],"response_format":{"type":"json_schema","json_schema":{"name":"smoke","strict":True,"schema":{"type":"object","properties":{"status":{"type":"string","enum":["IGGY_SCHEMA_OK"]}},"required":["status"],"additionalProperties":False}}}}),('tool_auto',{"messages":[{"role":"user","content":"Use get_weather to check the weather in Denver."}],"tools":[tool],"tool_choice":"auto"}),('tool_required',{"messages":[{"role":"user","content":"Use get_weather to check the weather in Denver."}],"tools":[tool],"tool_choice":"required"})]
records=[]
for name,p in items:
 p.update(model="flashnext-iggy",temperature=0,max_tokens=128,chat_template_kwargs={"enable_thinking":False})
 req=urllib.request.Request("http://litellm.llm.svc.cluster.local:4000/v1/chat/completions",data=json.dumps(p).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
 try:
  with urllib.request.urlopen(req,timeout=180) as f:d=json.load(f)
  msg=d["choices"][0]["message"]
  if name=="arithmetic":passed=msg["content"].strip()=="323"
  elif name=="json_object":passed=json.loads(msg["content"]).get("result")==323
  elif name=="schema":passed=json.loads(msg["content"])["status"]=="IGGY_SCHEMA_OK"
  else:passed=msg["tool_calls"][0]["function"]["name"]=="get_weather" and json.loads(msg["tool_calls"][0]["function"]["arguments"])["city"]=="Denver"
  records.append({"test":name,"passed":passed,"response":d})
 except urllib.error.HTTPError as e:records.append({"test":name,"passed":False,"status":e.code,"error":e.read().decode()})
 except Exception as e:records.append({"test":name,"passed":False,"error":str(e)})
print(json.dumps(records,indent=2))
'''
r=subprocess.run(k+['exec','-i','flashnext-iggy-stage','--','python3','-c',code],input=key.encode(),capture_output=True,check=True)
records=json.loads(r.stdout)
Path('/tmp/flashnext-competition/production-alias-smoke.json').write_text(json.dumps(records,indent=2)+'\n')
print('PRODUCTION_ALIAS_CHECKS',[(x['test'],x['passed'],x.get('status')) for x in records],flush=True)
required={'arithmetic','json_object','schema','tool_auto'}
assert all(x['passed'] for x in records if x['test'] in required),'Production alias fails a previously supported API check; inspect retained responses'
