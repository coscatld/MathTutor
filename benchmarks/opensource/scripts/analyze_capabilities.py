import os as _benchmark_os
"""Describe strengths and weaknesses from frozen test results, without retuning."""
from pathlib import Path
import json,csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties,fontManager
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
KEYS={'math_correct':'数学正确','addresses_student':'回应学生','actionable':'可执行性','instruction_following':'指令遵循','appropriate_disclosure':'披露适量','respectful':'尊重语气'}
def main():
 out=ROOT/'report';data=json.loads((out/'records.json').read_text());choice=json.loads((ROOT/'selection.json').read_text());candidate=choice['selected_run'];summary=json.loads((out/'summary.json').read_text());rows={run:[r for r in data[run]['test'] if 'criteria'in r] for run in ['baseline',candidate]}
 values={run:{k:sum(r['criteria'][k] for r in rr)/len(rr) for k in KEYS} for run,rr in rows.items()}
 font=next((p for p in [Path('/System/Library/Fonts/PingFang.ttc'),Path('/System/Library/Fonts/STHeiti Light.ttc')] if p.exists()),Path('/missing'))
 if font.exists():fontManager.addfont(str(font));plt.rcParams['font.family']=FontProperties(fname=str(font)).get_name()
 plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'axes.unicode_minus':False,'figure.facecolor':'white','font.size':12})
 fig,ax=plt.subplots(figsize=(12,5.5));xx=np.arange(len(KEYS))
 for run,label,color,offset in [('baseline','基线','#8793a3',-17),(candidate,'改进版','#245ac4',9)]:
  yy=[values[run][k]*100 for k in KEYS];ax.plot(xx,yy,'o-',label=label,color=color,linewidth=2)
  for x,y in zip(xx,yy):ax.annotate(f'{y:.1f}',(x,y),xytext=(0,offset),textcoords='offset points',ha='center',fontsize=11,color=color)
 ax.set_xticks(xx,list(KEYS.values()));ax.set_ylim(-3,110);ax.set_ylabel('标准满足率 / %');ax.grid(alpha=.18);ax.legend(frameon=False,loc='lower right');ax.set_title(f'能力维度对照 · 数学文本教学回应（每版 n={len(rows[candidate])}）',loc='left',fontweight='bold',pad=18)
 fig.subplots_adjust(top=.82,bottom=.23);fig.text(.08,.07,'Claude 独立评审；各维度分别计分。连线连接能力类别，不表示年级或学习进阶。\n仅比较本项目两版配置；没有与竞品同题测试。',fontsize=10,color='#5b6573')
 for ext in ['png','svg']:fig.savefig(out/f'capability_profile_lines.{ext}',dpi=190)
 plt.close(fig)
 four=json.loads((out/'four_benchmarks.json').read_text());sources=['MTB','MathDial','MRBench','TutorBench'];labels=['MathTutorBench','MathDial','MRBench','TutorBench']
 fig,axes=plt.subplots(2,1,figsize=(12,9));fig.subplots_adjust(top=.87,bottom=.15,hspace=.48)
 for ax,key,title in [(axes[0],'math_correct','数学正确项：MRBench 与 TutorBench 有回退'),(axes[1],'appropriate_disclosure','适量披露：TutorBench 回退，仍需改进')]:
  for run,label,color,offset in [('baseline','基线','#8793a3',-17),(candidate,'改进版','#245ac4',9)]:
   yy=[100*four[run][source]['criteria'][key] for source in sources];ax.plot(range(4),yy,'o-',label=label,color=color,linewidth=2)
   for x,y in enumerate(yy):
    peer=100*four['baseline' if run==candidate else candidate][sources[x]]['criteria'][key]
    dy=9 if y>peer or (y==peer and run==candidate) else -17
    ax.annotate(f'{y:.1f}%',(x,y),xytext=(0,dy),textcoords='offset points',ha='center',color=color,fontsize=10)
  ax.set_xticks(range(4),labels);ax.set_ylim(-3,110);ax.set_ylabel('标准满足率 / %');ax.set_title(title,loc='left',fontweight='bold',pad=16);ax.grid(alpha=.18);ax.legend(frameon=False,loc='lower right')
 fig.suptitle('四套基准的薄弱维度 · 综合分上升不代表每项都提高',fontsize=17,fontweight='bold',x=.07,ha='left')
 fig.text(.07,.04,'同一 Claude 评审标准；每版教学回应 n=96 / 24 / 24 / 47。模型评分不等于人类标签。\n各源题型、难度分布不同；小样本下降需在新封存集上复核，不能在本批题上调参后继续称为未见测试。',fontsize=10,color='#5b6573')
 for ext in ['png','svg']:fig.savefig(out/f'four_benchmarks_weakness_lines.{ext}',dpi=190)
 plt.close(fig)
 tab=[{'dimension':k,'label':KEYS[k],'baseline':values['baseline'][k],'candidate':values[candidate][k],'difference_pp':100*(values[candidate][k]-values['baseline'][k]),'n':len(rows[candidate])} for k in KEYS]
 with (out/'capability_dimensions.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(tab[0]));w.writeheader();w.writerows(tab)
 lines=['# 优势、弱势与改进优先级','', '结论来自本轮固定抽样的数学文本测试，只说明当前版本的相对强弱及相对基线变化，没有竞品比较，也不据此推断全年级或真实学生学习效果。','', '![能力维度折线图](capability_profile_lines.png)','', '| 维度 | 基线 | 改进版 | 变化（百分点） |','|---|---:|---:|---:|']
 for r in tab:lines.append(f'| {r["label"]} | {100*r["baseline"]:.2f}% | {100*r["candidate"]:.2f}% | {r["difference_pp"]:+.2f} |')
 ranked=sorted(summary[candidate]['test'].items(),key=lambda x:x[1].get('quality',-99),reverse=True);ranked=[(t,v)for t,v in ranked if 'quality'in v]
 lines+=['','## 相对优势','', '数值解题的明确最终答案正确率为 23/24（95.83%），和基线相同；它是本轮观察到的较强项，但样本较小，且只能说明标量答案子集。成功回答后去除无关练习、跟随当前语言和请求等修改，改善了可用性及部分格式遵循。','', '改进版教学综合分最高的三个任务如下。这是本轮任务间描述性排序，不是显著性排名：','']
 for task,v in ranked[:3]:lines.append(f'- {task}：六项均值 {100*v["quality"]:.2f}%，数学正确项 {100*v["criteria"]["math_correct"]:.2f}%，n={v["n"]}。')
 lines+=['','## 相对弱势','', '![四基准薄弱维度](four_benchmarks_weakness_lines.png)','', '高阶数学的数学正确项没有同步提升：统计为 17/23（73.91%），与基线相同；微积分从 22/24（91.67%）降至 21/24（87.50%），其适量披露从 100% 降至 75%。MRBench 数学正确项也从 21/24 降至 20/24。以上是模型评审与小样本观察，不能因综合均值上升而掩盖。TutorBench 加权细则仅提高约 3.64 个百分点，配对题组区间包含零，尚不足以证明稳定的细则收益。','', '纠错的明确最终答案诊断为 19/24（79.17%），基线为 20/24（83.33%）。逐题核对发现，4 条由对变零的样本均因最终句出现多个数值而不可解析，可见回答的结果正确，详见 `../OBJECTIVE_ERROR_AUDIT.md`；因此该下降不能证明真实纠错能力变差，本轮也不据此改解析器抬分。严格 Yes/No 格式正确率仅 25%，说明现有对话及工具封装仍难以稳定遵循极短的结构化输出约束。','', '教学综合分最低的三个任务如下：','']
 for task,v in sorted(ranked,key=lambda x:x[1]['quality'])[:3]:lines.append(f'- {task}：六项均值 {100*v["quality"]:.2f}%，数学正确项 {100*v["criteria"]["math_correct"]:.2f}%，n={v["n"]}。')
 lines+=['', '高级微积分、统计的加权细则与通用六项分应一起看：语气友好、句子通顺并不能补足遗漏的适用条件、概念辨析或学生误解诊断。第 2 轮开发集 TutorBench 仅小幅改善，未达到预设 +5 个百分点门槛；第 3 轮策略扩充后退步，已回退，不能声称质量门全部通过。','', '独立复核例：`TutorBench-Statistics-470` 能把组合数和概率乘积解释清楚，并声明二项近似，这是概念讲解的优点；但它照用了历史讲解中的错误小数。用高精度十进制独立计算，二项近似下 P(X≥2)=0.91404556，而回答给出约 0.912。暴露的弱点是未重新核对历史计算，本地验证器也并未覆盖所有显示算式；详见 `../results/statistics_470_arithmetic_check.json`。','', '## 可回放的薄弱案例','', '下列按固定样本 ID 排序，取改进版每个任务的第一条数学项失败或综合分低于 4/6 的回应；不是只挑成功案例。证据来自独立评审，需结合原输出人工复核。完整失败清单见 `failures.csv`。','']
 picked=set();cases=[]
 for r in sorted(rows[candidate],key=lambda x:x['id']):
  task=r['source']+'/'+r['task']
  if task in picked or (r['criteria']['math_correct'] and r['quality']>=4/6):continue
  picked.add(task);cases.append({'id':r['id'],'task':task,'criteria':r['criteria'],'evidence':r.get('judge_evidence',''),'reference_caveat':r.get('reference_caveat','')})
  lines.append(f'- `{r["id"]}`（{task}）：{r.get("judge_evidence","")}')
  if r.get('reference_caveat'):lines.append(f'  参考资料争议：{r["reference_caveat"]}')
 lines+=['','## 下一轮优先级','', '1. 增加独立、可核验的新开发题组，覆盖“计算对但问题解释错”、学生真正错误位置、统计检验条件和积分几何条件；先核对金标准，再用通用策略改进。','2. 为极短格式任务建立清晰的响应协议和可验证输出边界，同时保留正常教学对话能力；在新的封存集上验证。','3. 对披露量、针对性和可执行下一步逐项复核，避免靠增加问句或鼓励语取得表面高分。','4. 单列超时、部分完成与图形载荷，补充多轮真实交互及图片评测后，再讨论真实教学收益。','', '本轮测试已经解封。上述建议不在当前测试题上继续调参或挑答，后续必须使用新封存题组。','']
 (out/'STRENGTHS_WEAKNESSES.md').write_text('\n'.join(lines));(out/'capability_analysis.json').write_text(json.dumps({'dimensions':tab,'failure_examples':cases},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(values,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
