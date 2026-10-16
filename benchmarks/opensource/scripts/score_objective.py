import os as _benchmark_os
"""Frozen deterministic metrics; never changes prompts or generation outputs."""
from pathlib import Path
import argparse,json,re,collections,math
import sacrebleu
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
def clean(text):
    # Only application-added verification notices; never remove student-visible exercises.
    text=re.sub(r'^>[^\n]*(?:核验|核对|unverified|verified)[^\n]*\n*','',text,flags=re.I)
    return text.strip()
def last_num(s,commas=False):
    if commas:s=s.replace(',','')
    ns=re.findall(r'-?\d*\.?\d+',s)
    return float(ns[-1]) if ns else None
def score(r,g):
    task=r['task'];text=r.get('text','');body=clean(text);ok=r.get('status')=='COMPLETED';d={'id':r['id'],'source':r['source'],'task':task,'group':r['group'],'completed':int(ok),'score':None}
    if task in ['problem_solving','mistake_correction']:
        target=last_num(g['answer'].splitlines()[-1],True);native=last_num(text,task=='mistake_correction');adapted=last_num(body,task=='mistake_correction')
        markers=list(re.finditer(r'Final\s+answer\s*:?\*{0,2}\s*:',body,re.I))
        # Explicit label, optionally surrounded by Markdown. One scalar only;
        # multiple numbers after the label remain unparsed, never cherry-picked.
        if not markers:markers=list(re.finditer(r'Final\s+answer\s*:',body,re.I))
        segment=body[markers[-1].end():].strip().split('\n\n',1)[0] if markers else ''
        nums=re.findall(r'-?\d[\d,]*(?:\.\d+)?',segment)
        tagged=float(nums[0].replace(',','')) if len(nums)==1 else None
        d['tagged_answer_parsed']=int(tagged is not None)
        d['tagged_answer_score']=int(ok and tagged is not None and abs(tagged-target)<1e-6)
        d.update(score=int(ok and adapted is not None and abs(adapted-target)<1e-6),native_score=int(ok and native is not None and abs(native-target)<1e-6),target=target,prediction=adapted,final_marker=int(bool(re.search(r'Final\s+[Aa]nswer\s*:?\s*',body))))
    elif task=='solution_correctness':
        m=re.fullmatch(r'\s*\**\s*(yes|no)\s*[.!。]?\s*\**\s*',body,re.I);pred=m.group(1).lower()=='yes' if m else None
        low=text.lower();native=True if 'yes' in low else False if 'no' in low else True
        d.update(score=int(ok and pred is not None and pred==g['is_error']),native_score=int(ok and native==g['is_error']),parsed=int(pred is not None),target=g['is_error'],prediction=pred)
    elif task=='mistake_location':
        m=re.fullmatch(r'\s*\**\s*(\d+)\s*\**\s*[.!。]?\s*',body);pred=int(m.group(1)) if m else None
        nm=re.search(r'\d+',text);native=int(nm.group()) if nm else 0
        d.update(score=int(ok and pred==g['error_step']),native_score=int(ok and native==g['error_step']),parsed=int(pred is not None),target=g['error_step'],prediction=pred)
    elif task=='socratic_questioning':
        refs=[line.split(' ** ')[0] for line in g['answer'].splitlines() if len(line.split(' ** '))==2]
        native=max((sacrebleu.sentence_bleu(line.strip(),refs).score/100 for line in text.splitlines()),default=0) if refs and ok else 0
        d.update(score=native,native_score=native)
    else:
        q=('?' in text) or any(w in text.lower().split() for w in ['what','how','why','when','where','which','who','whose','whom','can','could','would'])
        d.update(question_rate=int(q),question_count=text.count('?')+text.count('？'))
    return d
def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--split',choices=['dev','test'],required=True);a=p.parse_args();gold=json.loads((ROOT/'private/gold.json').read_text());items=json.loads((ROOT/'public'/f'{a.split}.json').read_text());out=ROOT/'results'/a.run/a.split;scored=[]
    for x in items:
        f=out/(x['id']+'.json')
        if not f.exists():raise RuntimeError('missing case: '+x['id'])
        scored.append(score(json.loads(f.read_text()),gold[x['id']]))
    groups=collections.defaultdict(list)
    for r in scored:groups[r['source']+'/'+r['task']].append(r)
    summary={}
    for task,rs in groups.items():
        entry={'n':len(rs),'completed':sum(x['completed'] for x in rs),'unique_question_groups':len({x['group'] for x in rs})}
        for k in ['score','native_score','parsed','final_marker','question_rate','question_count','tagged_answer_score','tagged_answer_parsed']:
            vals=[r[k] for r in rs if r.get(k) is not None]
            if vals:entry[k]=sum(vals)/len(vals)
        summary[task]=entry
    (out/'objective_records.json').write_text(json.dumps(scored,indent=2)+'\n');(out/'objective_summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
