import os as _benchmark_os
"""Fetch public benchmark artifacts; preserve raw bytes and provenance."""
from pathlib import Path
import concurrent.futures,hashlib,json,ssl,time,urllib.request,subprocess
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])));DATA=ROOT/'data';DATA.mkdir(exist_ok=True)
CTX=ssl.create_default_context(cafile='/etc/ssl/cert.pem')
def fetch(name,url):
    path=DATA/name
    if path.exists() and (not name.startswith('TutorBench_rows_') or 'rows' in json.loads(path.read_text())):return path
    for attempt in range(3):
        try:
            temp=path.with_suffix(path.suffix+'.download')
            status=subprocess.check_output(['curl','-L','--retry','2','--max-time','120','--cacert','/etc/ssl/cert.pem','-sS',url,'-o',str(temp),'-w','%{http_code}'],text=True)
            if status != '200':
                temp.unlink(missing_ok=True)
                raise RuntimeError('HTTP '+status)
            body=temp.read_bytes();temp.unlink();etag=None
            path.write_bytes(body)
            meta={'source_url':url,'downloaded_at':time.time(),'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'etag':etag}
            path.with_suffix(path.suffix+'.source.json').write_text(json.dumps(meta,indent=2)+'\n')
            print(json.dumps({'file':name,'bytes':len(body)}),flush=True);return path
        except Exception as e:
            print(json.dumps({'file':name,'attempt':attempt+1,'error_type':type(e).__name__,'detail':str(e)[:160]}),flush=True)
            if attempt==2:raise RuntimeError('public download failed: '+name) from None
            time.sleep(2**attempt)
def main():
    tasks=[(f'TutorBench_rows_{n:04d}.json',f'https://datasets-server.huggingface.co/rows?dataset=ScaleAI%2FTutorBench&config=default&split=train&offset={n}&length=100') for n in range(0,1473,100)]
    tasks += [('stepverify_parquet.json','https://datasets-server.huggingface.co/parquet?dataset=eth-nlped%2Fstepverify'),('gsm8k_parquet.json','https://datasets-server.huggingface.co/parquet?dataset=openai%2Fgsm8k')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda t:fetch(*t),tasks))
    jobs=[]
    for stem in ['stepverify','gsm8k']:
        meta=json.loads((DATA/f'{stem}_parquet.json').read_text())
        for i,f in enumerate(meta.get('parquet_files',[])):
            name=f'{stem}_{f["config"]}_{f["split"]}_{i:02d}.parquet'
            jobs.append((name,f['url']))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda t:fetch(*t),jobs))
if __name__=='__main__':main()
