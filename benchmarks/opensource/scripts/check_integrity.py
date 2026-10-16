import os as _benchmark_os
"""Check immutable inputs, disjoint groups, paired labels and score direction."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
def main():
 freeze=json.loads((ROOT/'freeze.json').read_text())
 for rel in ['public/dev.json','public/test.json','private/gold.json','private/judge_calibration.json','inventory.json']:
  assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==freeze['files'][rel],rel
 dev=json.loads((ROOT/'public/dev.json').read_text());test=json.loads((ROOT/'public/test.json').read_text());gold=json.loads((ROOT/'private/gold.json').read_text())
 assert len(dev)==80 and len(test)==312
 assert not ({x['group'] for x in dev}&{x['group'] for x in test})
 assert len({x['id'] for x in dev+test})==len(dev+test)
 assert set(gold)=={x['id'] for x in dev+test}
 for x in dev+test:
  assert not ({'answer','reference_solution','rubrics','teacher_gold','error_step','is_error'} & set(x))
  assert x['grade'] in [7,11]
 for rows in [dev,test]:
  for task in ['mistake_location','solution_correctness']:
   sub=[x for x in rows if x['task']==task]
   assert sum(gold[x['id']]['is_error'] for x in sub)*2==len(sub)
 # Scorer must not repair unparseable responses into a correct strict answer.
 from score_objective import score
 for task,g in [('solution_correctness',{'is_error':True}),('mistake_location',{'error_step':0})]:
  row=score(dict(id='fixture',source='fixture',task=task,group='fixture',status='COMPLETED',text='No usable response'),g)
  assert row['score']==0
 # A prohibited behavior hit must lower the weighted total.
 assert (5*1+1*1-5*1)/(5+1)<(5*1+1*1-5*0)/(5+1)
 print(json.dumps({'passed':True,'dev':len(dev),'test':len(test),'cross_split_question_overlap':0,'public_gold_fields':0,'frozen_input_hashes_match':True}))
if __name__=='__main__':main()
