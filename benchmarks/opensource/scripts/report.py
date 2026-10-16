import os as _benchmark_os
"""Aggregate frozen runs; paired group bootstrap; export charts and tables."""
from pathlib import Path
import json,collections,csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties,fontManager
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])));OUT=ROOT/'report';OUT.mkdir(exist_ok=True)
CANDIDATE=json.loads((ROOT/'selection.json').read_text())['selected_run']
DEV_REVIEW={'baseline':['baseline_dev'],'candidate_r1':['candidate_r1_dev','candidate_r1_dev_remainder'],'candidate_r2':['candidate_r2_dev'],'candidate_r3b':['candidate_r3b_dev']}
KEYS=['math_correct','addresses_student','actionable','instruction_following','appropriate_disclosure','respectful']
LABELS={'MTB/problem_solving':'解题','MTB/mistake_correction':'纠错','MTB/solution_correctness':'错误识别','MTB/mistake_location':'错误位置','MTB/socratic_questioning':'苏格拉底提问','MTB/scaffolding_generation':'脚手架','MTB/pedagogy_following':'教学遵循','MTB/scaffolding_generation_hard':'脚手架 hard','MTB/pedagogy_following_hard':'教学遵循 hard','MathDial/next_turn':'MathDial','MRBench/next_turn':'MRBench','TutorBench/Calculus':'微积分','TutorBench/Statistics':'统计'}
def read(p):return json.loads(p.read_text())
def reviews(labels,run):return [x for label in labels for x in read(ROOT/'review'/label/'parsed.json') if x['run']==run]
def records(run,split):
    rows=read(ROOT/'results'/run/split/'objective_records.json');idx={r['id']:r for r in rows}
    labels=DEV_REVIEW[run] if split=='dev' else ['final_test']
    judged=reviews(labels,run)
    for j in judged:
        r=idx[j['id']];r.update(quality=j['quality'],criteria=j['criteria'])
        if 'rubric_score'in j:r['rubric_score']=j['rubric_score']
        if 'labels'in j:r['mr_labels']=j['labels']
        r['judge_evidence']=j.get('evidence','');r['reference_caveat']=j.get('reference_caveat','')
    expected=sum(r['score'] is None for r in rows)
    assert len(judged)==expected and len({j['id'] for j in judged})==expected,(run,split,len(judged),expected)
    return rows

def ci(rows,key):
    sub=[r for r in rows if key in r and r[key] is not None]
    groups=collections.defaultdict(list)
    for r in sub:groups[r['group']].append(float(r[key]))
    gs=list(groups);rng=np.random.default_rng(20261016)
    if not gs:return None
    means=[]
    for _ in range(2000):
        sample=rng.choice(gs,len(gs),replace=True);vals=[v for g in sample for v in groups[g]];means.append(np.mean(vals))
    return [float(np.quantile(means,.025)),float(np.quantile(means,.975))]
def aggregate(rows):
    by=collections.defaultdict(list)
    for r in rows:by[r['source']+'/'+r['task']].append(r)
    out={}
    for task,rr in by.items():
        item={'n':len(rr),'groups':len({r['group'] for r in rr}),'completed':sum(r['completed'] for r in rr)}
        for k in ['score','native_score','tagged_answer_score','tagged_answer_parsed','parsed','quality','rubric_score','question_rate']:
            vals=[r[k] for r in rr if r.get(k) is not None]
            if vals:item[k]=float(np.mean(vals));item[k+'_ci95']=ci(rr,k)
        if 'criteria' in rr[0]:item['criteria']={k:float(np.mean([r['criteria'][k] for r in rr])) for k in KEYS}
        out[task]=item
    return out

def main():
    font=next((p for p in [Path('/System/Library/Fonts/PingFang.ttc'),Path('/System/Library/Fonts/STHeiti Light.ttc')] if p.exists()),Path('/missing'))
    if font.exists():fontManager.addfont(str(font));plt.rcParams['font.family']=FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.alpha':.18,'figure.facecolor':'white','axes.unicode_minus':False,'font.size':11})
    data={run:{s:records(run,s) for s in (['dev','test'] if run in ['baseline',CANDIDATE] else ['dev'])} for run in DEV_REVIEW}
    unfiltered_summary={run:aggregate(ss['test']) for run,ss in data.items() if 'test' in ss}
    (OUT/'original_312_sensitivity.json').write_text(json.dumps(unfiltered_summary,ensure_ascii=False,indent=2)+'\n')
    excluded=set(read(ROOT/'exclusions.json')['excluded_test_ids'])
    for ss in data.values():
        if 'test' in ss:ss['test']=[r for r in ss['test'] if r['id'] not in excluded]
    summary={run:{s:aggregate(rows) for s,rows in ss.items()} for run,ss in data.items()}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    table=[]
    for run,ss in summary.items():
        for split,tasks in ss.items():
            for task,m in tasks.items():
                for metric in ['score','native_score','tagged_answer_score','tagged_answer_parsed','parsed','quality','rubric_score','question_rate']:
                    if metric in m:table.append({'run':run,'split':split,'task':task,'metric':metric,'value':m[metric],'n':m['n'],'groups':m['groups'],'ci95_low':m[metric+'_ci95'][0],'ci95_high':m[metric+'_ci95'][1]})
    with (OUT/'metrics.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    colors={'baseline':'#8793a3',CANDIDATE:'#245ac4'}
    def line(ax,tasklist,key,title,ylim=(0,100)):
        xx=np.arange(len(tasklist))
        for run,label in [('baseline','基线'),(CANDIDATE,'改进版')]:
            vals=[summary[run]['test'][t][key]*100 for t in tasklist]
            ax.plot(xx,vals,'o-',label=label,color=colors[run],linewidth=2,markersize=6)
            other='baseline' if run==CANDIDATE else CANDIDATE
            for x,v,t in zip(xx,vals,tasklist):
                peer=summary[other]['test'][t][key]*100
                above=v>peer or (v==peer and run==CANDIDATE) or v<8
                ax.annotate(f'{v:.1f}',(x,v),xytext=(0,7 if above else -15),textcoords='offset points',ha='center',fontsize=9,color=colors[run])
        ax.set_xticks(xx,[LABELS[t] for t in tasklist]);ax.set_ylim(*ylim);ax.set_title(title,loc='left',fontweight='bold',pad=16);ax.set_ylabel('%');ax.legend(frameon=False,loc='best')
    fig,axes=plt.subplots(2,2,figsize=(14,9.4));fig.subplots_adjust(hspace=.43,wspace=.24,top=.88,bottom=.10)
    line(axes[0,0],['MTB/problem_solving','MTB/mistake_correction'],'tagged_answer_score','最终标记数值正确率（各 n=24）')
    line(axes[0,1],['MTB/solution_correctness','MTB/mistake_location'],'score','严格格式正确率（各 n=24；12 个题组）')
    line(axes[1,0],['TutorBench/Calculus','TutorBench/Statistics'],'rubric_score','TutorBench 加权 rubric（微积分 24，统计 23）',(-20,105))
    ax=axes[1,1];bleu=[summary[run]['test']['MTB/socratic_questioning']['score']*100 for run in ['baseline',CANDIDATE]]
    ax.plot([0,1],bleu,'o-',color='#245ac4',linewidth=2);ax.set_xticks([0,1],['基线','改进版']);ax.set_ylim(0,100);ax.set_ylabel('%');ax.set_title('苏格拉底 BLEU 相似度（n=24；不是正确率）',loc='left',fontweight='bold',pad=16)
    for x,v in enumerate(bleu):ax.annotate(f'{v:.1f}',(x,v),xytext=(0,8),textcoords='offset points',ha='center')
    fig.suptitle('MathTutor 开源数学文本评测 · 固定样本 · 311 条隔离后测试集',fontsize=18,fontweight='bold',x=.06,ha='left')
    fig.text(.06,.025,'不同指标分面展示；连线仅连接任务类别，不表示年级进阶。单次生成，失败计入分母。隔离 1 道近重复题；区间见 metrics.csv。',fontsize=10,color='#5b6573')
    for ext in ['png','svg']:fig.savefig(OUT/f'test_metrics_lines.{ext}',dpi=190)
    plt.close(fig)
    tasks=['MTB/scaffolding_generation','MTB/pedagogy_following','MTB/scaffolding_generation_hard','MTB/pedagogy_following_hard','MathDial/next_turn','MRBench/next_turn','TutorBench/Calculus','TutorBench/Statistics']
    fig,ax=plt.subplots(figsize=(14,5.5));line(ax,tasks,'quality','教学回应质量：六项标准均值（n=24，统计 n=23；Claude 独立评审）',(-3,105));ax.tick_params(axis='x',labelrotation=15);fig.subplots_adjust(bottom=.23,top=.84)
    fig.text(.06,.04,'模型评审分数不是人工评分或学生学习增益；评审器的人类标签校准结果单列。',fontsize=10,color='#5b6573')
    for ext in ['png','svg']:fig.savefig(OUT/f'teaching_quality_lines.{ext}',dpi=190)
    plt.close(fig)
    runs=list(DEV_REVIEW);xx=np.arange(len(runs));fig,axes=plt.subplots(1,3,figsize=(14,4.8));fig.subplots_adjust(wspace=.32,bottom=.22,top=.80)
    for ax,key,title in zip(axes,['quality','rubric_score','tagged_answer_score'],['回应质量（40 条）','TutorBench rubric（16 条）','最终标记数值正确率（16 条）']):
        vals=[np.mean([r[key] for r in data[run]['dev'] if key in r])*100 for run in runs]
        ax.plot(xx,vals,'o-',color='#245ac4',linewidth=2);ax.set_xticks(xx,['基线','第 1 轮','第 2 轮','第 3 轮']);ax.set_title(title,fontsize=12);ax.set_ylim(-5,105);ax.set_ylabel('%')
        for x,v in zip(xx,vals):ax.annotate(f'{v:.1f}',(x,v),xytext=(0,8),textcoords='offset points',ha='center',fontsize=10)
    fig.suptitle('开发集迭代轨迹 · 用于调参，不作为最终泛化成绩',fontsize=17,fontweight='bold',x=.06,ha='left')
    fig.text(.06,.04,'所有轮次完整保留；数值指标使用明确最终标记诊断，避免将清理追加文本误当作数学能力提升。',fontsize=10,color='#5b6573')
    for ext in ['png','svg']:fig.savefig(OUT/f'development_iterations.{ext}',dpi=190)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.8));fig.subplots_adjust(bottom=.22,top=.80,wspace=.28)
    for ax,tasks,key,title in [(axes[0],['MTB/problem_solving','MTB/mistake_correction'],'native_score','源末尾数值解析分数'),(axes[1],['MTB/solution_correctness','MTB/mistake_location'],'parsed','严格格式可解析率')]:
        line(ax,tasks,key,title,(-5,110))
    fig.suptitle('输出格式诊断 · 与数学能力分别解释',fontsize=16,fontweight='bold',x=.06,ha='left')
    fig.text(.06,.04,'无关追加练习会污染末尾数字解析；主图另列最终标记诊断，不能将此处提升全算作推理提升。',fontsize=10,color='#5b6573')
    for ext in ['png','svg']:fig.savefig(OUT/f'format_diagnostics_lines.{ext}',dpi=190)
    plt.close(fig)
    # Four source benchmarks share only the explicit six-item adapted teaching measure.
    source_order=['MTB','MathDial','MRBench','TutorBench']
    source_labels=['MathTutorBench','MathDial','MRBench','TutorBench']
    four={}
    for run in ['baseline',CANDIDATE]:
        four[run]={}
        for source in source_order:
            rr=[r for r in data[run]['test'] if r['source']==source and 'quality' in r]
            four[run][source]={'n':len(rr),'quality':float(np.mean([r['quality'] for r in rr])),'quality_ci95':ci(rr,'quality'),'criteria':{k:float(np.mean([r['criteria'][k] for r in rr])) for k in KEYS}}
    (OUT/'four_benchmarks.json').write_text(json.dumps(four,ensure_ascii=False,indent=2)+'\n')
    fig,ax=plt.subplots(figsize=(12,5.7));fig.subplots_adjust(bottom=.25,top=.80)
    xx=np.arange(4)
    for run,label in [('baseline','基线'),(CANDIDATE,'改进版')]:
        yy=[four[run][source]['quality']*100 for source in source_order]
        ax.plot(xx,yy,'o-',label=label,color=colors[run],linewidth=2.3,markersize=7)
        for x,v in zip(xx,yy):ax.annotate(f'{v:.1f}%',(x,v),xytext=(0,10 if run==CANDIDATE else -18),textcoords='offset points',ha='center',color=colors[run],fontsize=11)
    ax.set_xticks(xx,[f'{label}\n教学回应 n={four[CANDIDATE][source]["n"]}' for source,label in zip(source_order,source_labels)]);ax.set_ylim(-3,110);ax.set_ylabel('六项教学标准满足率 / %');ax.legend(frameon=False,loc='lower right')
    fig.suptitle('四套开源基准 · 数学文本教学质量对照',fontsize=18,fontweight='bold',x=.07,ha='left')
    fig.text(.07,.055,'统一适配的六项标准，由 Claude 独立评审；不是各原基准的官方总分。\nMathTutorBench 此图仅含 4 类教学回应任务；各源题型与难度分布不同。连线连接基准类别，不表示年级进阶。',fontsize=10,color='#5b6573')
    for ext in ['png','svg']:fig.savefig(OUT/f'four_benchmarks_lines.{ext}',dpi=190)
    plt.close(fig)
    # Paired improvements with question-group bootstrap, preserving cross-task duplication.
    paired={};base={r['id']:r for r in data['baseline']['test']};cand={r['id']:r for r in data[CANDIDATE]['test']}
    for key in ['quality','rubric_score','score','tagged_answer_score']:
        diffs=[{'group':base[i]['group'],'difference':cand[i][key]-base[i][key]} for i in base if key in base[i] and base[i][key] is not None and key in cand[i]]
        # Heterogeneous objective scores are never pooled: score is emitted per task below.
        if key=='score':continue
        paired[key]={'n':len(diffs),'mean_difference':float(np.mean([r['difference'] for r in diffs])),'group_bootstrap_ci95':ci(diffs,'difference')}
    (OUT/'paired_differences.json').write_text(json.dumps(paired,indent=2)+'\n')
    mrtable=[]
    for run in ['baseline',CANDIDATE]:
        rr=[r for r in data[run]['test'] if r['source']=='MRBench']
        assert len(rr)==24 and all('mr_labels' in r for r in rr)
        dims=['Mistake_Identification','Mistake_Location','Providing_Guidance','Actionability','Coherence','Humanlikeness','Revealing_of_the_Answer','Tutor_Tone']
        for dim in dims:
            values=collections.Counter(r['mr_labels'][dim] for r in rr)
            for label,count in sorted(values.items()):mrtable.append({'run':run,'dimension':dim,'label':label,'count':count,'n':len(rr),'proportion':count/len(rr)})
    with (OUT/'mrbench_dimensions.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(mrtable[0]));w.writeheader();w.writerows(mrtable)
    (OUT/'records.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    failures=[]
    for run,ss in data.items():
        for split,rows in ss.items():
            for r in rows:
                if not r['completed'] or r.get('score')==0 or r.get('criteria',{}).get('math_correct')==0:
                    failures.append({'run':run,'split':split,'id':r['id'],'source':r['source'],'task':r['task'],'completed':r['completed'],'objective_score':r.get('score'),'judged_math_correct':r.get('criteria',{}).get('math_correct'),'rubric_score':r.get('rubric_score'),'judge_evidence':r.get('judge_evidence',''),'reference_caveat':r.get('reference_caveat','')})
    if failures:
        with (OUT/'failures.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(failures[0]));w.writeheader();w.writerows(failures)
    print(json.dumps({'charts':5,'csv_rows':len(table),'paired':paired},indent=2))
if __name__=='__main__':main()
