import ast,json,hashlib
from pathlib import Path
r=Path('/tmp/flashnext-competition');name='stew-q6-classic-r15-full-qualification'
original=json.loads((r/'stew-q6-classic-r15.json').read_text());p=json.loads(json.dumps(original));p['metadata']['name']='flashnext-'+name;(r/(name+'.json')).write_text(json.dumps(p,indent=2)+'\n');assert p['spec']==original['spec']
(r/'q6-classic-full-plan.json').write_text(json.dumps({'profile':name,'screen_profile':'stew-q6-classic-r15','spec_byte_identity':p['spec']==original['spec'],'spec_sha256':hashlib.sha256(json.dumps(p['spec'],sort_keys=True).encode()).hexdigest(),'completed_screen':'6matchingC1+14exactnoncealone/concurrentreplay+4independentC2+3APIchecks; all256 outputs reviewedcoherent. Longpair841.65307s, noOOM.','remaining_protocols':'9publishedraw trials +16AiderPP including32K/64K +14exactreplayafter64KPP +3APIchecks','reason':'Do notrepeatalready-passing longC1/C2 timing screen withoutconfigchange. Post64Kreplay checksbatch2 output afternewmaximummeasuredprefill/buffer growth.','reuse':'Reportcommon/C2timingsfromoriginalscreen andPP/rawfromidenticalfullprofile; no fakecommon preconditioning file or overwrittenoriginaltrials.'},indent=2)+'\n')
s=(r/'profile-c2-replay.py').read_text();s=s.replace("common_path=a.output.parent/(a.profile+'-common.json')","common_path=a.output.parent/(a.profile+'-pp.json')")
s=s.replace("assert len(common['trials'])==6 and all(t.get('ok') for t in common['trials'])","assert len(common['trials'])==16 and all(t.get('ok') for t in common['trials'])")
s=s.replace("assert common['trials'][-1]['label'].startswith('common40890-3-')","assert common['trials'][-1]['label'].startswith('pp65536-2-')")
s=s.replace("'trials':6,'last_label'","'protocol':'pp','trials':16,'last_label'")
s=s.replace('INITIAL_ORIGINAL_PAIR_AFTER_COMMON','INITIAL_ORIGINAL_PAIR_AFTER_64K_PP')
s=s.replace('Exact original anomalous C2 pair, SHA-256 verified, repeated unchanged C1 then C2; floating-point output differences are recorded, not automatically classified as corruption','Exact original anomalous C2 pair after completed16trial8K/32K/64KPP sweep, SHA-256 verified, repeated unchanged C1 then C2; differences recorded for manualqualityreview')
ast.parse(s);(r/'profile-c2-replay-postpp.py').write_text(s)
f=r/'run-profile.py';s=f.read_text();needle="   if protocol=='replay':args[args.index(remote+'/flashnext_public_bench.py')]=remote+'/profile-c2-replay.py'";assert needle in s;s=s.replace(needle,needle+"\n   if protocol=='postpp-replay':args[args.index(remote+'/flashnext_public_bench.py')]=remote+'/profile-c2-replay-postpp.py'");ast.parse(s);f.write_text(s)
for fn,needle,repl in [
 ('copy-local-evidence.py',"'stew-q6-all-cache-c1-reserve4-full']",f"'stew-q6-all-cache-c1-reserve4-full','{name}']"),
 ('copy-local-evidence.py',"'stew-q6-all-cache-c1-reserve4-full-memory-screen-decision.json']","'stew-q6-all-cache-c1-reserve4-full-memory-screen-decision.json','q6-classic-full-plan.json']"),
 ('render-performance-tables.py',"name+'-pp', name+'-c2') for title,name","('stew-q6-classic-r15-full-qualification-pp' if name=='stew-q6-classic-r15' else name+'-pp'), name+'-c2') for title,name"),
 ('render-raw-decode-table.py',"lines=['| Raw profile",f"profiles += [('Q6 conservative two-slot, full qualification','{name}')]\nlines=['| Raw profile")]:
 f=r/fn;s=f.read_text();assert needle in s,fn;s=s.replace(needle,repl);ast.parse(s);f.write_text(s)
print('CLASSIC_FULL_PROFILE_IDENTICAL_SPEC_AND_POST_PP_REPLAY_PREPARED')
