"""Fixed-seed policy evaluation with a separate synthetic response oracle."""
import argparse,hashlib,json,logging,random,statistics,sys,time
from collections import Counter
from fractions import Fraction
from pathlib import Path
ROOT=Path(__file__).resolve().parent
REPO=next(p for p in (ROOT/'repo',*ROOT.parents) if (p/'src/mathtutor').is_dir())
sys.path.insert(0,str(REPO/'src'))
from mathtutor.learning import diagnostic_probes as dp


def oracle(probe,rule):
    # Independent implementation: does not call prediction or grading helpers.
    if probe.domain=='signed_subtraction':
        left,right=probe.operands
        if rule=='correct': result=left-right
        elif rule=='ignore_subtracted_sign': result=left-right if right>=0 else left+right
        elif rule=='always_negative_difference':
            result=abs(left)-abs(right)
            if result>0: result=-result
        elif rule=='add_instead': result=sum((left,right))
        else: raise ValueError(rule)
        return Fraction(result,1)
    left_num,left_den,right_num,right_den=probe.operands
    if rule=='correct':
        return Fraction(left_num*right_den+right_num*left_den,left_den*right_den)
    if rule=='add_across':
        return Fraction(sum((left_num,right_num)),sum((left_den,right_den)))
    if rule=='multiply_denominators':
        return (Fraction(left_num,1)+Fraction(right_num,1))/left_den/right_den
    if rule=='keep_left_denominator':
        return Fraction(left_num,left_den)+Fraction(right_num,left_den)
    raise ValueError(rule)


def response(case,probe,step):
    condition=case['condition']; rule=case['rule']
    if condition=='slip_first':
        return oracle(probe,'correct')+(1 if step==0 else 0)
    if condition=='strategy_switch':
        # A real change in behavior, no invented simulator learning benefit.
        error_rule=dp.RULES[probe.domain][1+(case['noise_seed']%3)]
        return oracle(probe,error_rule if step==0 else 'correct')
    if condition=='unknown_rule': return oracle(probe,'correct')+97
    # The other mechanism uses a lookup that mimics a known rule exactly.
    # Its causal identity cannot be inferred from this response transcript.
    return oracle(probe,rule)


def run_case(case,policy,latencies):
    observations=[]; chosen=[]
    pool=[p for p in dp.catalog(case['domain']) if p.purpose=='diagnostic' and p.probe_id not in case['excluded_ids']]
    if policy=='random': random.Random(case['noise_seed']).shuffle(pool)
    for step in range(3):
        state=dp.diagnostic_state(case['domain'],observations)
        if state['status']!='collecting': break
        start=time.perf_counter()
        if policy=='active': probe=dp.choose_probe(case['domain'],observations,case['excluded_ids'])
        else: probe=next((p for p in pool if p.probe_id not in chosen),None)
        elapsed=(time.perf_counter()-start)*1000
        if probe is None: break
        latencies.append(elapsed)
        answer=response(case,probe,step)
        observations.append({'probe_id':probe.probe_id,'answer':str(answer),'independent':True})
        chosen.append(probe.probe_id)
    state=dp.diagnostic_state(case['domain'],observations)
    return {'episode_id':case['episode_id'],'domain':case['domain'],'condition':case['condition'],
        'policy':policy,'expected_rule':case['rule'] if case['condition']=='known' else None,
        'supported_rule':state['supported_rule'],'status':state['status'], 'questions':len(chosen),
        'observations':observations}


def summarize(rows):
    known=[r for r in rows if r['condition']=='known']
    correct=[r for r in known if r['supported_rule']==r['expected_rule']]
    wrong=[r for r in known if r['supported_rule'] is not None and r['supported_rule']!=r['expected_rule']]
    stress={}
    for condition in ('slip_first','strategy_switch','unknown_rule','indistinguishable_other'):
        items=[r for r in rows if r['condition']==condition]
        stress[condition]={'episodes':len(items),'provisional_matches':sum(r['supported_rule'] is not None for r in items),
            'uncertain':sum(r['supported_rule'] is None for r in items)}
    return {'known_episodes':len(known),'correct_supported':len(correct),'wrong_supported':len(wrong),
        'correct_coverage':len(correct)/len(known) if known else None,
        'mean_questions_to_correct_support':statistics.mean(r['questions'] for r in correct) if correct else None,
        'mean_questions_all_known':statistics.mean(r['questions'] for r in known) if known else None,
        'stress':stress,'max_questions':max(r['questions'] for r in rows)}


def main():
    parser=argparse.ArgumentParser()
    for name in ('data-dir','checkpoint-dir','output-dir'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--seed',type=int,default=0);parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args()
    if args.seed!=0:parser.error('Registered seed is 0')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s',
        handlers=[logging.FileHandler(args.output_dir/'eval.log'),logging.StreamHandler()])
    start=time.perf_counter()
    manifest=json.loads((args.checkpoint_dir/'manifest.json').read_text())
    fixtures=args.data_dir/'fixtures.json'
    source=REPO/'src/mathtutor/learning/diagnostic_probes.py'
    assert hashlib.sha256(fixtures.read_bytes()).hexdigest()==manifest['fixtures_sha256']
    assert hashlib.sha256(source.read_bytes()).hexdigest()==manifest['core_sha256']
    cases=json.loads(fixtures.read_text())
    if args.smoke: cases=[c for c in cases if c['domain']=='fraction_addition' and int(c['episode_id'].rsplit(':',1)[1])<8]
    data_load_seconds=time.perf_counter()-start
    # Verify all served catalog items mathematically before the first episode.
    compile_start=time.perf_counter()
    domains=sorted({c['domain'] for c in cases})
    catalogs={d:dp.catalog(d) for d in domains}
    compile_seconds=time.perf_counter()-compile_start
    rows=[]; latencies=[];results={};latencies_by_policy={}
    for policy in ('active','fixed','random'):
        policy_start=time.perf_counter()
        policy_latencies=[]
        policy_rows=[run_case(case,policy,policy_latencies) for case in cases]
        latencies_by_policy[policy]=policy_latencies
        latencies+=policy_latencies
        rows+=policy_rows
        results[policy]={d:summarize([r for r in policy_rows if r['domain']==d]) for d in domains}
        logging.info('%s: %s episodes in %.6fs',policy,len(cases),time.perf_counter()-policy_start)
    gate=None
    if not args.smoke:
        active=results['active']['signed_subtraction'];controls=[results[p]['signed_subtraction'] for p in ('fixed','random')]
        coverage_branch=all(active['correct_coverage']-c['correct_coverage']>=.10-1e-12 for c in controls)
        efficiency_branch=all(c['mean_questions_to_correct_support'] is not None and active['correct_coverage']>=c['correct_coverage'] and active['mean_questions_to_correct_support']<=.85*c['mean_questions_to_correct_support'] for c in controls)
        gate={'coverage_branch':coverage_branch,'efficiency_branch':efficiency_branch,'passed':coverage_branch or efficiency_branch,
            'selected_branch':'coverage_at_three_questions' if coverage_branch else 'efficiency_at_nonlower_coverage' if efficiency_branch else 'none'}
    def timing(values):
        ordered=sorted(values)
        return {'p50':statistics.median(values),'p95':ordered[int(.95*(len(ordered)-1))], 'max':max(values),'samples':len(values)}
    report={'seed':0,'training':False,'population':'synthetic','smoke':args.smoke,
        'results':results,'primary_gate':gate,'data_load_seconds':data_load_seconds,'catalog_compile_seconds':compile_seconds,
        'total_seconds':time.perf_counter()-start,'selection_latency_ms':{'scope':'all_policies_combined',**timing(latencies)},
        'selection_latency_ms_by_policy':{policy:timing(values) for policy,values in latencies_by_policy.items()},
        'catalog_sizes':{d:len(c) for d,c in catalogs.items()},'served_catalog_math_gate':'PASS',
        'manifest':manifest,'caveat':'Provisional output patterns only. Unknown lookup mechanisms can be observationally identical; no stable misconception attribution or student learning gain is validated.'}
    (args.output_dir/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (args.output_dir/'episodes.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    logging.info('Complete: runtime %.6fs; primary gate %s; active p95 %.6fms',report['total_seconds'],gate,report['selection_latency_ms_by_policy']['active']['p95'])
    print(json.dumps({'results':results,'primary_gate':gate,'total_seconds':report['total_seconds']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
