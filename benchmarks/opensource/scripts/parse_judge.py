import os as _benchmark_os
"""Validate independent judge outputs without silently repairing scores."""
from pathlib import Path
import argparse,json,re,collections
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
KEYS=['math_correct','addresses_student','actionable','instruction_following','appropriate_disclosure','respectful']
DIMS=['Mistake_Identification','Mistake_Location','Providing_Guidance','Actionability','Coherence','Humanlikeness','Revealing_of_the_Answer','Tutor_Tone']
def read(p):return json.loads(p.read_text())
def normalize(k,v):
 if k=='Revealing_of_the_Answer':
  if v.lower().startswith('no'):return 'No'
  return 'Yes (incorrect)' if 'incorrect' in v.lower() else 'Yes (correct)'
 return v.strip()
def main():
 p=argparse.ArgumentParser();p.add_argument('label');a=p.parse_args();folder=ROOT/'review'/a.label;mapping=read(folder/'blind_mapping.json');manifest=read(folder/'manifest.json');allrows=[];metadata=[]
 for prompt in sorted(folder.glob('*.prompt.txt')):
  f=prompt.with_suffix('.raw.json');raw=read(f)
  if raw.get('is_error'):raise RuntimeError(str(f)+' judge reported error')
  result=raw.get('result','').strip();result=re.sub(r'^```(?:json)?\s*|\s*```$','',result)
  normalized=prompt.with_suffix('.normalized.json')
  rows=read(normalized) if normalized.exists() else json.loads(result)
  if isinstance(rows,dict):rows=rows.get('results',rows.get('assessments'))
  assert isinstance(rows,list),f
  expected=json.loads(prompt.read_text().split('\nDATA:\n',1)[1].split('\nEnd of data.',1)[0]);assert {r['id'] for r in rows}=={r['id'] for r in expected},f
  lookup={r['id']:r for r in expected}
  for row in rows:
   blind_id=row['id'];ref=lookup[blind_id];row.update(mapping[blind_id]);row['blind_id']=blind_id
   if manifest['mode']=='responses':
    assert set(row['criteria'])==set(KEYS),(f,row['id'])
    assert all(type(v) is int and v in [0,1] for v in row['criteria'].values())
    # Failed subject calls always zero in the primary complete-case denominator.
    if ref.get('status')!='COMPLETED':row['criteria']={k:0 for k in KEYS};row['failure_zeroed']=True
    row['quality']=sum(row['criteria'].values())/len(KEYS)
    if 'rubrics' in ref:
     rub=ref['rubrics'];valid={i for i,z in enumerate(rub) if z['attributes'].get('severity')!='deleted'}
     assert {v['index'] for v in row['rubrics']}==valid,(f,row['id'],'rubric coverage')
     numerator=denominator=0
     for v in row['rubrics']:
      assert type(v['hit']) is int and v['hit'] in [0,1]
      sev=rub[v['index']]['attributes']['severity'];w={'critical':5,'not_critical':1,'critical_negative':-5}[sev];numerator+=w*v['hit'];denominator+=max(w,0)
     row['rubric_score']=numerator/denominator if denominator else 0
     if ref.get('status')!='COMPLETED':row['rubric_score']=0
   allrows.append(row)
  metadata.append({'file':f.name,'modelUsage':raw.get('modelUsage'),'duration_ms':raw.get('duration_ms'),'cost_usd':raw.get('total_cost_usd')})
 assert len(allrows)==len(mapping) and len({r['blind_id'] for r in allrows})==len(mapping)
 (folder/'parsed.json').write_text(json.dumps(allrows,ensure_ascii=False,indent=2)+'\n');(folder/'judge_usage.json').write_text(json.dumps(metadata,indent=2)+'\n')
 if manifest['mode']=='calibration':
  summary={}
  for dim in DIMS:
   matches=[];pairs=collections.Counter()
   for r in allrows:
    g={k.lower():v for k,v in r['gold'].items()};pred={k.lower():v for k,v in r['labels'].items()}
    if dim.lower() not in g or dim.lower() not in pred:raise RuntimeError('missing dimension '+dim)
    a1=normalize(dim,g[dim.lower()]);b=normalize(dim,pred[dim.lower()]);matches.append(a1==b);pairs[a1+' -> '+b]+=1
   summary[dim]={'n':len(matches),'agreement':sum(matches)/len(matches),'pairs':dict(pairs)}
  (folder/'agreement.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
 else:
  groups=collections.defaultdict(list)
  for r in allrows:groups[r['run']].append(r)
  print(json.dumps({k:{'n':len(v),'quality':sum(r['quality'] for r in v)/len(v),'rubric_mean':sum(r['rubric_score'] for r in v if 'rubric_score'in r)/max(1,sum('rubric_score'in r for r in v))} for k,v in groups.items()},indent=2))
if __name__=='__main__':main()
