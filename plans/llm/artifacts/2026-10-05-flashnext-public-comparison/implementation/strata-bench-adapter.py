"""Add raw benchmark routes to Strata's official HTTP frontend; localhost only.

Engine, tokenizer, chat rendering and streaming chat routes remain upstream.
Raw completions run the same resident StrataEngine.generate token protocol.
"""
import contextlib,json,sys,threading,time
from pathlib import Path
root=Path('/workspace/flashnext-competition/strata/src')
sys.path.insert(0,str(root))
import serve.server as S
original=S.make_handler

def adapted(svc):
    class Handler(original(svc)):
        def do_GET(self):
            if self.path=='/stats':
                return self._json(200,{'engine':svc.engine.info,'last':svc.engine.last,'adapter':'raw stdio; upstream chat'})
            return super().do_GET()
        def do_POST(self):
            if self.path not in ('/tokenize','/v1/completions'):
                return super().do_POST()
            req=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
            ids=svc.tok.encode(req.get('prompt',req.get('content','')),parse_special=True)
            if self.path=='/tokenize':
                return self._json(200,{'count':len(ids),'tokens':ids})
            max_new=int(req.get('max_tokens',256))
            if len(ids)+max_new>svc.engine.max_context:
                return self._json(400,{'error':'context limit'})
            if req.get('ignore_eos'):
                # Engine's EOS list is fixed at startup; do not silently claim parity.
                return self._json(400,{'error':'per-request ignore_eos unsupported'})
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.send_header('Cache-Control','no-cache')
            self.end_headers()
            detok=S.Detokenizer(svc.tok); n=0
            def send(d):
                self.wfile.write(('data: '+json.dumps(d)+'\n\n').encode());self.wfile.flush()
            lock=contextlib.nullcontext() if svc.engine.batch else svc.fifo
            with lock:
                for token in svc.engine.generate(ids,max_new,req,threading.Event()):
                    if token is None:
                        self.wfile.write(b': heartbeat\n\n');self.wfile.flush();continue
                    n+=1
                    send({'choices':[{'index':0,'text':detok.push(token),'finish_reason':None}]})
                last=dict(svc.engine.last)
            send({'choices':[{'index':0,'text':'','finish_reason':'length' if n>=max_new else 'stop'}],
                  'usage':{'prompt_tokens':len(ids),'completion_tokens':n,'total_tokens':len(ids)+n,
                           'prompt_tokens_details':{'cached_tokens':last.get('reused',0)}}})
            self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
    return Handler
S.make_handler=adapted
if __name__=='__main__':
    if '--host' in sys.argv and sys.argv[sys.argv.index('--host')+1]!='127.0.0.1':
        raise SystemExit('benchmark adapter must bind localhost')
    raise SystemExit(S.main())
