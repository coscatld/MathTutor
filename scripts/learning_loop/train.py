"""Freeze the non-training policy and fixtures without evaluating held-out data."""
import argparse, hashlib, json, logging, random, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
REPO = next(p for p in (ROOT/'repo', *ROOT.parents) if (p/'src/mathtutor').is_dir())
sys.path.insert(0, str(REPO/'src'))
from mathtutor.learning import diagnostic_probes as dp


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--checkpoint-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=0)
    args=parser.parse_args()
    if args.seed != 0: parser.error('This registered experiment uses seed=0 only')
    for path in (args.data_dir,args.checkpoint_dir,args.output_dir): path.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[logging.FileHandler(args.output_dir/'train.log'),logging.StreamHandler()])
    start=time.perf_counter()
    # Development-domain compilation only; no held-out inference or fitting.
    dev=dp.catalog('fraction_addition')
    compile_seconds=time.perf_counter()-start
    rng=random.Random(args.seed)
    cases=[]
    for domain in dp.DOMAINS:
        diagnostic_count=25 if domain=='fraction_addition' else 36
        for condition in ('known','slip_first','strategy_switch','unknown_rule','indistinguishable_other'):
            count=200 if condition=='known' else 50
            for index in range(count):
                rule=dp.RULES[domain][index % 4]
                excluded=sorted(rng.sample(range(diagnostic_count),index%7))
                cases.append({'episode_id':f'{domain}:{condition}:{index:03}', 'domain':domain,
                    'condition':condition,'rule':rule,'noise_seed':rng.randrange(2**31),
                    'excluded_ids':[f'{domain}:diagnostic:{i:02}' for i in excluded]})
    fixtures=args.data_dir/'fixtures.json'
    fixtures.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    source=REPO/'src/mathtutor/learning/diagnostic_probes.py'
    manifest={'seed':0,'training':False,'weights_fitted':False,'baseline_commit':'f6f928b7c3de0e9d98b8c303ad66c4cba20ca74d',
        'policy_version':dp.POLICY_VERSION,'core_sha256':sha(source),'fixtures_sha256':sha(fixtures),
        'development_domain':'fraction_addition','heldout_domain':'signed_subtraction',
        'cases_per_domain':400,'known_per_domain':200,'stress_per_domain':200,
        'models':list(dp.RULES.items()),'max_questions':3,'source_of_labels':'independent elementary-formula simulator',
        'generalization_scope':'generic selection policy across two authored domains; not discovery of new rules',
        'stress_warning':'indistinguishable_other deliberately duplicates known outputs; no finite observation can identify its cause',
        'development_compile_seconds':compile_seconds,'full_runtime_seconds':time.perf_counter()-start,
        'gpu':'N/A; deterministic CPU policy, no training'}
    (args.checkpoint_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    logging.info('Frozen %s cases, %s development probes; training=false; compile %.6fs; total %.6fs',len(cases),len(dev),compile_seconds,manifest['full_runtime_seconds'])

if __name__=='__main__': main()
