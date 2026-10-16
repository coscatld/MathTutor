import os as _benchmark_os
"""Run only after development freezes a candidate and records any unmet guards."""
from pathlib import Path
import json,subprocess,os,sys,time,hashlib
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
def run(*args,env=None):subprocess.run([sys.executable,*map(str,args)],env=env,check=True)
def main():
    deadline=time.monotonic()+1800
    while not (ROOT/'selection.json').exists():
        if time.monotonic()>deadline:raise RuntimeError('Selection has not finished')
        time.sleep(5)
    choice=json.loads((ROOT/'selection.json').read_text());assert 'selected_run' in choice,choice
    name=choice['selected_run'];manifest=json.loads((ROOT/'sources'/(name+'.json')).read_text())
    env=dict(os.environ,PYTHONPATH=manifest['path']+'/src',MT_SOURCE_DIGEST=manifest['source_sha256'])
    print('Frozen candidate: '+name,flush=True)
    run(ROOT/'scripts/run_product.py','--split','test','--config',_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_CONFIG', '/tmp/local-benchmark.json'),'--output',ROOT/'results'/name/'test','--workers','12',env=env)
    for version in ['baseline',name]:run(ROOT/'scripts/score_objective.py','--run',version,'--split','test')
    run(ROOT/'scripts/judge.py','--mode','responses','--runs','baseline',name,'--split','test','--label','final_test','--workers','12')
    run(ROOT/'scripts/normalize_judge.py','final_test')
    run(ROOT/'scripts/parse_judge.py','final_test')
    run(ROOT/'scripts/report.py')
if __name__=='__main__':main()
