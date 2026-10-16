import os as _benchmark_os
"""Only public inputs; each case gets fresh process/app/database. No gold import."""
import argparse,concurrent.futures,hashlib,json,os,tempfile,time,signal
from pathlib import Path
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
def one(item,config,outdir):
    def timeout(*_):raise TimeoutError('case exceeded 420 seconds')
    signal.signal(signal.SIGALRM,timeout);signal.alarm(420)
    from mathtutor.evaluation.tutor_multiturn import _client,_send,_turn_view
    from mathtutor.infrastructure import db_crypto
    from mathtutor.infrastructure.secret_store import InMemorySecretStore
    db_crypto.use_keystore(InMemorySecretStore());live=json.loads(Path(config).read_text());trace=[]
    def prepare(state):
        from mathtutor.infrastructure.generative_gateway import ModelRole
        for role in ModelRole:
            state.gateway.provider_for(role).provider_id = "deepseek"
        state.learner_settings.update('middle' if item['grade']<=9 else 'high',item['grade'])
        original=state.gateway.complete
        async def tracked(role,messages,**kwargs):
            start=time.monotonic();r={'role':str(role),'messages':messages,'settings':{k:v for k,v in kwargs.items() if isinstance(v,(str,int,float,bool,type(None)))}}
            try:
                v=await original(role,messages,**kwargs);r.update(text=v.text,model=v.model,provider_id=v.provider_id,finish_reason=v.finish_reason,input_tokens=v.input_tokens,output_tokens=v.output_tokens);return v
            except Exception as e:r['error_type']=type(e).__name__;raise
            finally:r['duration_s']=time.monotonic()-start;trace.append(r)
        state.gateway.complete=tracked
    record={'id':item['id'],'source':item['source'],'task':item['task'],'group':item['group'],'prompt':item['prompt'],'started_at':time.time()};start=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='mt-open-case-') as tmp:
            with _client(Path(tmp)/'synthetic.db',live,prepare) as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
                frames=_send(ws,item['id'],'send_message','initial',{'text':item['prompt']})
                record.update(_turn_view(frames));record['events']=frames
    except Exception as e:record.update(text='',status='RUNNER_ERROR',errors=[type(e).__name__])
    record.update(duration_s=time.monotonic()-start,trace=trace);signal.alarm(0)
    p=Path(outdir)/(item['id']+'.json');p.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str)+'\n')
    return {'id':item['id'],'status':record['status'],'calls':len(trace),'seconds':round(record['duration_s'],1)}
def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['dev','test'],required=True);p.add_argument('--config',required=True);p.add_argument('--output',required=True);p.add_argument('--workers',type=int,default=12);p.add_argument('--limit',type=int);a=p.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True);data=ROOT/'public'/f'{a.split}.json';items=json.loads(data.read_text());items.sort(key=lambda x:hashlib.sha256(x['id'].encode()).hexdigest())
    if a.limit:items=items[:a.limit]
    manifest={'started_at':time.time(),'n':len(items),'split':a.split,'model':json.loads(Path(a.config).read_text())['model'],'source_path':os.environ.get('PYTHONPATH'),'source_digest':os.environ.get('MT_SOURCE_DIGEST'),'input_sha256':hashlib.sha256(data.read_bytes()).hexdigest(),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'workers':a.workers,'temperature':'product default (0.4 writer)','order':[x['id'] for x in items],'retries':'none; completed files are never replaced'}
    mp=out/'run_manifest.json'
    if mp.exists():
        old=json.loads(mp.read_text());assert old['input_sha256']==manifest['input_sha256'] and old['source_digest']==manifest['source_digest']
    else:mp.write_text(json.dumps(manifest,indent=2)+'\n')
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers,max_tasks_per_child=1) as pool:
        jobs=[pool.submit(one,x,a.config,str(out)) for x in items if not (out/(x['id']+'.json')).exists()]
        for f in concurrent.futures.as_completed(jobs):print(json.dumps(f.result()),flush=True)
if __name__=='__main__':main()
