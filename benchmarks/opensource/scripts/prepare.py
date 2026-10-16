import os as _benchmark_os
"""Freeze public inputs and judge-only gold before subject calls. No score input."""
from pathlib import Path
import json,re,hashlib,collections,random
import pyarrow.parquet as pq
import yaml
from jinja2 import Template
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])));SRC=ROOT.parent
SEED='MathTutor-open-20261016-v1'
def norm(s):return re.sub(r'[^\w]','',str(s).casefold().replace('_',''))
def sha(s):return hashlib.sha256(s.encode()).hexdigest()
def readj(p):return json.loads(p.read_text())
def jl(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def rows(p):return pq.read_table(p).to_pylist()
def save(p,d):p.parent.mkdir(exist_ok=True,parents=True);p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def main():
    gsm={s:rows(ROOT/'data'/f'gsm8k_main_{s}_{"00" if s=="test" else "01"}.parquet') for s in ['train','test']}
    soc={s:rows(ROOT/'data'/f'gsm8k_socratic_{s}_{"02" if s=="test" else "03"}.parquet') for s in ['train','test']}
    step=rows(ROOT/'data/stepverify_default_train_00.parquet')
    bridges={n:readj(SRC/'mathtutorbench/datasets'/f'mathdial_bridge{n}.json') for n in ['', '_hard']}
    md={s:jl(SRC/'mathdial/data'/f'{s}.jsonl') for s in ['train','test']}
    mr=readj(SRC/'UnifyingAITutorEvaluation/MRBench/MRBench_V2.json')
    tb=[]
    for i in range(0,1473,100):
        d=readj(ROOT/'data'/f'TutorBench_rows_{i:04d}.json');assert 'rows' in d,(i,d.keys())
        tb.extend(x['row'] for x in d['rows'])
    assert len(tb)==1473 and len({r['TASK_ID'] for r in tb})==1473
    allquestions={norm(r['question']):r['question'] for r in gsm['train']+gsm['test']+md['train']+md['test']}
    allquestions.update({norm(r['problem']):r['problem'] for r in step+bridges['']+bridges['_hard']})
    # Find exact normalized question embedded in MRBench histories. No answers used.
    def mrquestion(r):
        h=norm(r['conversation_history']);hits=[q for n,q in allquestions.items() if n and n in h]
        if hits:return max(hits,key=len)
        first=re.split(r'\bStudent:',r['conversation_history'],flags=re.I)[0]
        return re.sub(r'^Tutor:\s*','',first).strip()
    for r in mr:r['_question']=mrquestion(r)
    reserved={norm(r['question']) for r in gsm['test']+md['test']}
    reserved.update(norm(r['_question']) for r in mr if r['Split']=='test')
    def split(q):return 'test' if norm(q) in reserved else ('dev' if int(sha(SEED+norm(q))[:8],16)%4==0 else 'test')
    cal_candidates=[r for r in mr if split(r['_question'])=='dev']
    cal_candidates.sort(key=lambda r:sha(SEED+r['conversation_id']))
    cal=cal_candidates[:8];calgroups={sha(norm(r['_question'])) for r in cal}
    pool=[];gold={};inventory=[]
    def add(source,task,index,q,prompt,private,grade=11,origin=''):
        group=sha(norm(q))
        if group in calgroups:return
        ident=f'{source}-{task}-{index}'
        pool.append(dict(id=ident,source=source,task=task,group=group,split=split(q),prompt=prompt,grade=grade,origin=origin))
        gold[ident]=dict(question=q,**private)
    for task in ['problem_solving','socratic_questioning']:
        cfg=yaml.safe_load((SRC/'mathtutorbench/configs'/f'{task}.yaml').read_text())
        for s in ['train','test']:
            for i,r in enumerate((gsm if task=='problem_solving' else soc)[s]):
                # Keep official GSM8K train out of held-out sample; test never development.
                if split(r['question'])!=('dev' if s=='train' else 'test'):continue
                prompt=Template(cfg['system_prompt']).render(question=r['question'],shots=cfg['few_shot_samples'])
                add('MTB',task,f'{s}{i}',r['question'],prompt,{'answer':r['answer']},7,s)
    for task,config in [('solution_correctness','student_solution_correctness'),('mistake_location','mistake_location'),('mistake_correction','mistake_correction')]:
        cfg=yaml.safe_load((SRC/'mathtutorbench/configs'/f'{config}.yaml').read_text())
        for i,r in enumerate(step):
            dialog=r['dialog_history'];cut=next((j for j,t in enumerate(dialog) if t['user']=='Student'),len(dialog))
            hist='\n'.join('Teacher: '+t['text'] for t in dialog[:cut])
            for error in ([True] if task=='mistake_correction' else [True,False]):
                steps=r['student_incorrect_solution'][:-1] if error else r['reference_solution'].split('\n')[:-1]
                ss='\\n'.join(f'Step {j+1} - {t}' for j,t in enumerate(steps))
                chat=dialog[cut]['text'] if error else r['student_correct_response']
                prompt=Template(cfg['system_prompt']).render(question=r['problem'],shots=cfg['few_shot_samples'],dialog_history=hist,student_solution=ss,student_chat_solution=chat)
                add('MTB',task,f'{i}{"w" if error else "c"}',r['problem'],prompt,{'answer':r['reference_solution'],'is_error':error,'error_step':int(r['incorrect_index'])+1 if error else 0},7,'stepverify/train')
    for suffix,data in bridges.items():
        for base in ['scaffolding_generation','pedagogy_following']:
            task=base+suffix;cfg=yaml.safe_load((SRC/'mathtutorbench/configs'/f'{task}.yaml').read_text())
            for i,r in enumerate(data):
                hist='\n'.join(t['user']+': '+t['text'] for t in r['dialog_history'][:-1])
                prompt=Template(cfg['system_prompt']).render(question=r['problem'],shots=cfg['few_shot_samples'],dialog_history=hist)
                add('MTB',task,str(i),r['problem'],prompt,{'answer':r['reference_solution'],'teacher_gold':r['dialog_history'][-1]['text']},7,'bridge'+suffix)
    for s,data in md.items():
        for i,r in enumerate(data):
            if s=='train' and split(r['question'])!='dev':continue
            if s=='test' and split(r['question'])!='test':continue
            turns=[re.sub(r'^(Teacher|Student):\s*\([^)]*\)',r'\1: ',t).strip() for t in r['conversation'].split('|EOM|')]
            cut=next((j for j,t in enumerate(turns[:-1]) if t.startswith('Student:') and turns[j+1].startswith('Teacher:')),None)
            if cut is None:continue
            prompt='Respond as the tutor to the student’s latest message. Give focused guidance without solving unrequested later steps.\nProblem: '+r['question']+'\nConversation:\n'+'\n'.join(turns[:cut+1])+'\nTutor:'
            add('MathDial','next_turn',f'{s}{i}',r['question'],prompt,{'answer':r['ground_truth'],'teacher_gold':turns[cut+1]},7,s)
    for i,r in enumerate(mr):
        prompt='Respond as the tutor to the student’s latest message. Give focused guidance without solving unrequested later steps.\nConversation:\n'+r['conversation_history']+'\nTutor:'
        add('MRBench','next_turn',str(i),r['_question'],prompt,{'answer':r['Ground_Truth_Solution']},7,r['Split'])
    eligible=[]
    for i,r in enumerate(tb):
        if r['SUBJECT'] not in ['Calculus','Statistics'] or 'TEXT' not in r['BATCH'] or r['IMAGE_URL']:continue
        eligible.append(r)
        prompt='Problem:\n'+r['PROMPT']
        if r['UC1_INITIAL_EXPLANATION']:prompt+='\nPrevious explanation:\n'+r['UC1_INITIAL_EXPLANATION']
        if r['FOLLOW_UP_PROMPT']:prompt+='\nStudent’s latest message:\n'+r['FOLLOW_UP_PROMPT']
        prompt+='\nRespond to the student’s latest request.'
        add('TutorBench',r['SUBJECT'],str(i),r['PROMPT'],prompt,{'rubrics':json.loads(r['RUBRICS']),'batch':r['BATCH']},11,r['TASK_ID'])
    # Fixed quota by task, no output-dependent selection. Preserve wrong/correct pairs.
    selected=[]
    for source,task in sorted({(x['source'],x['task']) for x in pool}):
        for s in ['dev','test']:
            sub=[x for x in pool if (x['source'],x['task'],x['split'])==(source,task,s)]
            groups=collections.defaultdict(list)
            for x in sub:groups[x['group']].append(x)
            quota=(8 if s=='dev' else 24)
            if source=='TutorBench':quota=8 if s=='dev' else 24 # per subject
            order=sorted(groups,key=lambda g:sha(SEED+source+task+g))
            chosen=[]
            for g in order:
                members=sorted(groups[g],key=lambda x:sha(SEED+x['id']))
                # Paired verifiers: take one correct and one wrong from same source row.
                if task in ['solution_correctness','mistake_location']:
                    base=members[0]['id'][:-1];members=[x for x in members if x['id'][:-1]==base]
                else:members=members[:1]
                if len(chosen)+len(members)>quota:continue
                chosen+=members
                if len(chosen)>=quota:break
            selected+=chosen
            inventory.append({'source':source,'task':task,'split':s,'eligible_records':len(sub),'eligible_groups':len(groups),'selected':len(chosen)})
    for s in ['dev','test']:save(ROOT/'public'/f'{s}.json',[x for x in selected if x['split']==s])
    assert not ({x['group'] for x in selected if x['split']=='dev'} & {x['group'] for x in selected if x['split']=='test'})
    save(ROOT/'private/gold.json',{x['id']:gold[x['id']] for x in selected})
    save(ROOT/'private/judge_calibration.json',cal)
    save(ROOT/'inventory.json',{'seed':SEED,'sampling':'fixed SHA-256 ranking, task-stratified; sampled adapted evaluation, not official leaderboard','counts':inventory,'TutorBench_total':len(tb),'TutorBench_math_text':len(eligible),'TutorBench_excluded_images_or_nonmath':len(tb)-len(eligible),'TutorBench_subjects':dict(collections.Counter(x['SUBJECT'] for x in tb)),'TutorBench_batches':dict(collections.Counter(x['BATCH'] for x in tb)),'calibration_contexts':len(cal),'totals':dict(collections.Counter(x['split'] for x in selected))})
    files=[ROOT/'public/dev.json',ROOT/'public/test.json',ROOT/'private/gold.json',ROOT/'private/judge_calibration.json',ROOT/'inventory.json',Path(__file__)]
    save(ROOT/'freeze.json',{'created_at':__import__('time').time(),'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'group_overlap':0})
    print(json.dumps(readj(ROOT/'inventory.json'),ensure_ascii=False))
if __name__=='__main__':main()
