"""Record semantic and structured-API probes without executing model tool calls."""
import argparse,json,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--endpoint',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--model',default='qwen3.8-flash-next');a=p.parse_args()
base={'model':a.model,'temperature':0,'seed':7,'max_tokens':512,'chat_template_kwargs':{'enable_thinking':False}}
cases=[('arithmetic',{'messages':[{'role':'user','content':'What is 17 multiplied by 19? Reply with the number only.'}]}),('json',{'messages':[{'role':'user','content':'Return a JSON object with product equal to 17 multiplied by 19 and ok equal to true. No explanation.'}],'response_format':{'type':'json_object'}}),('tool',{'messages':[{'role':'user','content':'Call get_weather to look up the current weather in Denver. Use the tool rather than guessing.'}],'tools':[{'type':'function','function':{'name':'get_weather','description':'Look up weather for a city','parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}}],'tool_choice':'auto'})]
records=[]
for name,extra in cases:
 record={'case':name}
 try:
  req=urllib.request.Request(a.endpoint+'/v1/chat/completions',data=json.dumps({**base,**extra}).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=240) as r:j=json.load(r)
  record['response']=j;m=j['choices'][0]['message'];text=m.get('content') or ''
  if name=='arithmetic':record['passed']=text.strip()=='323'
  elif name=='json':v=json.loads(text);record['passed']=v.get('product')==323 and v.get('ok') is True
  else:
   calls=m.get('tool_calls') or [];record['passed']=len(calls)==1 and calls[0]['function']['name']=='get_weather' and json.loads(calls[0]['function']['arguments']).get('city','').lower()=='denver'
 except Exception as e:record.update(passed=False,error=str(e))
 records.append(record);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(records,indent=2)+'\n');print(name,record['passed'],flush=True)
