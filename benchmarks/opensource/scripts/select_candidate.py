import os as _benchmark_os
"""Select only from complete development results; held-out results never read."""
from pathlib import Path
import json,time,subprocess,sys,hashlib
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
LABELS={'baseline':['baseline_dev'],'candidate_r1':['candidate_r1_dev','candidate_r1_dev_remainder'],'candidate_r2':['candidate_r2_dev'],'candidate_r3b':['candidate_r3b_dev']}
def main():
    # Wait for actual saved judge output, not arbitrary elapsed time as evidence.
    deadline=time.monotonic()+1800
    while time.monotonic()<deadline:
        ready=True
        for labels in LABELS.values():
            for label in labels:
                folder=ROOT/'review'/label
                for f in folder.glob('*.prompt.txt'):
                    raw=f.with_suffix('.normalized.json')
                    if not raw.exists() or not raw.stat().st_size:ready=False
        if ready:break
        time.sleep(5)
    else:raise RuntimeError('Development judge outputs incomplete')
    for labels in LABELS.values():
        for label in labels:subprocess.run([sys.executable,str(ROOT/'scripts/parse_judge.py'),label],check=True)
    summary={}
    for run,labels in LABELS.items():
        rr=[r for label in labels for r in json.loads((ROOT/'review'/label/'parsed.json').read_text())]
        assert len(rr)==40 and len({r['id'] for r in rr})==40
        objective=json.loads((ROOT/'results'/run/'dev/objective_summary.json').read_text())
        summary[run]={'quality':sum(r['quality'] for r in rr)/len(rr),'math_correct':sum(r['criteria']['math_correct'] for r in rr)/len(rr),'rubric':sum(r['rubric_score'] for r in rr if 'rubric_score'in r)/16,'tagged_numeric':sum(objective[t]['tagged_answer_score'] for t in ['MTB/problem_solving','MTB/mistake_correction'])/2}
    b=summary['baseline']
    eligible=[run for run in LABELS if run!='baseline' and summary[run]['quality']>=b['quality']+.05 and summary[run]['rubric']>=b['rubric']+.05 and summary[run]['math_correct']>=b['math_correct'] and summary[run]['tagged_numeric']>=b['tagged_numeric']]
    out={'frozen_at':time.time(),'decision_rule':'Development quality and TutorBench weighted rubric each at least 5 percentage points above baseline; judged math correctness and final-marker numeric accuracy do not decline. Highest quality among eligible candidates. Rule frozen before complete dev judge aggregation and held-out scoring.','development':summary,'eligible':eligible}
    if eligible:
        best=max(eligible,key=lambda r:summary[r]['quality']);source=json.loads((ROOT/'sources'/(best+'.json')).read_text());out.update(selected_run=best,source_sha256=source['source_sha256'],reason='Meets frozen development guards; three general product iterations completed. No held-out data read for selection.')
    else:out['requires_more_development']=True
    (ROOT/'selection.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
