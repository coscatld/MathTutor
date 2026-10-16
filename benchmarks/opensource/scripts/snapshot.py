import os as _benchmark_os
"""Capture tracked baseline + explicit product edits, never unrelated user files."""
import argparse,subprocess,tarfile,io,hashlib,json,time
from pathlib import Path
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])));REPO=ROOT.parents[1]/'MathTutor'
FILES=['src/mathtutor/application/controller.py','src/mathtutor/application/function_graph.py','src/mathtutor/application/teaching_intent.py','src/mathtutor/infrastructure/tutor_chat.py','tests/test_tutor_multilingual_requests.py','src/mathtutor/application/input_math_checks.py','tests/test_input_math_checks.py']
def main():
 p=argparse.ArgumentParser();p.add_argument('label');a=p.parse_args();out=ROOT/'sources';out.mkdir(exist_ok=True)
 base=subprocess.check_output(['git','archive','b2ad094'],cwd=REPO);dst=Path('/tmp')/('mathtutor-os-'+a.label+'-20261016');dst.mkdir(exist_ok=False)
 with tarfile.open(fileobj=io.BytesIO(base)) as tf:tf.extractall(dst,filter='data')
 present=[f for f in FILES if (REPO/f).exists()]
 for f in present:(dst/f).write_bytes((REPO/f).read_bytes())
 hashes={str(f.relative_to(dst)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted((dst/'src').rglob('*.py'))}
 digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
 patch=subprocess.check_output(['git','diff','--',*FILES],cwd=REPO);(out/(a.label+'.patch')).write_bytes(patch)
 with tarfile.open(out/(a.label+'.tar.gz'),'w:gz') as tf:tf.add(dst,arcname=a.label)
 manifest={'label':a.label,'baseline_commit':'b2ad094a9c664d7289f1fd23e82f53c2640491bd','created_at':time.time(),'path':str(dst),'source_sha256':digest,'files':hashes,'changed_files':present}
 (out/(a.label+'.json')).write_text(json.dumps(manifest,indent=2)+'\n');print(digest)
if __name__=='__main__':main()
