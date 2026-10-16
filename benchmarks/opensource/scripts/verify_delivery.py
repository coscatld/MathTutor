import os as _benchmark_os
"""Final coverage, source identity and immutable input verification."""
from pathlib import Path
import json,hashlib,subprocess,sys
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
def main():
 subprocess.run([sys.executable,str(ROOT/'scripts/check_integrity.py')],check=True)
 selected=json.loads((ROOT/'selection.json').read_text())['selected_run'];source=json.loads((ROOT/'sources'/(selected+'.json')).read_text());repo=ROOT.parents[1]/'MathTutor'
 actual_source={str(f.relative_to(repo)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (repo/'src').rglob('*.py')}
 assert actual_source==source['files'],'Product source differs from selected snapshot'
 for rel in source['changed_files']:
  assert (repo/rel).read_bytes()==(Path(source['path'])/rel).read_bytes(),rel
 public={s:json.loads((ROOT/'public'/f'{s}.json').read_text()) for s in ['dev','test']};results={}
 for run in ['baseline','candidate_r1','candidate_r2','candidate_r3b']:
  for split in (['dev','test'] if run in ['baseline',selected] else ['dev']):
   expected={x['id'] for x in public[split]};folder=ROOT/'results'/run/split
   actual={f.stem for f in folder.glob('*.json') if f.stem.startswith(('MTB-','TutorBench-','MRBench-','MathDial-'))};assert expected==actual,(run,split)
   results[run+'/'+split]=len(actual)
 parsed=json.loads((ROOT/'review/final_test/parsed.json').read_text());expected={(run,x['id']) for run in ['baseline',selected] for x in public['test'] if x['task'] not in ['problem_solving','mistake_correction','solution_correctness','mistake_location','socratic_questioning']}
 assert {(r['run'],r['id']) for r in parsed}==expected
 files={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(ROOT.rglob('*')) if f.is_file() and f.name not in ['delivery_manifest.json'] and '__pycache__' not in f.parts}
 out={'verified':True,'case_counts':results,'final_judgments':len(parsed),'delivered_product_source_matches_selected':True,'files':files}
 (ROOT/'delivery_manifest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='files'},indent=2))
if __name__=='__main__':main()
