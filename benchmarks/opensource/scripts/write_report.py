import os as _benchmark_os
"""Write the report only from completed artifacts; no score edits or reranking."""
from pathlib import Path
import json,collections,time
ROOT=Path(_benchmark_os.environ.get('MATHTUTOR_BENCHMARK_ROOT', str(Path(__file__).resolve().parents[1])))
def read(p):return json.loads(p.read_text())
def pct(v):return f'{100*v:.2f}%'
def mean(rows,k):return sum(r[k] for r in rows)/len(rows)
def main():
 summary=read(ROOT/'report/summary.json');choice=read(ROOT/'selection.json');candidate=choice['selected_run'];data=read(ROOT/'report/records.json');base=data['baseline']['test'];cand=data[candidate]['test'];pair=read(ROOT/'report/paired_differences.json');cal=read(ROOT/'review/calibration/agreement.json');commit=read(ROOT/'product_commit.json')['commit'];s=summary
 bq=[r for r in base if 'quality'in r];cq=[r for r in cand if 'quality'in r];br=[r for r in base if 'rubric_score'in r];cr=[r for r in cand if 'rubric_score'in r]
 statuses={}
 for run in ['baseline',candidate]:
  pub=read(ROOT/'public/test.json');rs=[read(ROOT/'results'/run/'test'/(x['id']+'.json')) for x in pub];statuses[run]=dict(collections.Counter(r['status'] for r in rs))
 source=read(ROOT/'source_manifest.json');lines=[]
 lines += ['# MathTutor 开源数学文本评测报告','',f'日期：2026-10-16。被测配置：DeepSeek Flash，writer 温度 0.4；独立评审：Claude Opus 4.7。采纳产品代码：`{commit}`。','',f'本轮完成 80 条开发样本的基线及三轮策略复测，并对基线和冻结的第 2 轮分别生成全部 312 条测试回答。评分前依据题干近重复检查隔离 1 条，主要分析使用 **311 条、{len({r["group"] for r in base})} 个规范化题组**。所有原始回答保留；没有对低分题重新生成或按题择优。','',f'教学回应六项标准满足率由 **{pct(mean(bq,"quality"))} → {pct(mean(cq,"quality"))}**（各 {len(bq)} 条）；TutorBench 加权 rubric 由 **{pct(mean(br,"rubric_score"))} → {pct(mean(cr,"rubric_score"))}**（各 {len(br)} 条）。这些是独立模型评审结果，不是人类标签或学生学习增益。','', '开发阶段第 2 轮综合质量最高，故冻结该轮。第 3 轮退步并回退。三轮均未满足预设的 TutorBench +5 个百分点开发门槛，`passed_all_guards=false`；本轮不宣称已通过全部教学质量发布门。','', '高阶数学没有随综合分同步提升：统计数学正确项维持 73.91%；微积分从 91.67% 降至 87.50%，适量披露从 100% 降至 75%。MRBench 数学正确项从 87.50% 降至 83.33%。这些下降完整保留，属于模型评审下的小样本观察。','', '## 结果图','', '![四套基准折线图](report/four_benchmarks_lines.png)','', '四个点分别代表四套基准。统一六项教学标准用于跨基准描述；各源原生指标仍分别报告。MathTutorBench 的此项仅覆盖其 4 类教学回应任务。','', '![封存测试集各指标折线图](report/test_metrics_lines.png)','', '![薄弱维度折线图](report/four_benchmarks_weakness_lines.png)','', '优势弱势的详细证据与优先级见 [能力分析](report/STRENGTHS_WEAKNESSES.md)。','', '![教学回应质量折线图](report/teaching_quality_lines.png)','', '![开发迭代折线图](report/development_iterations.png)','', '## 数值与格式结果','', '![格式诊断折线图](report/format_diagnostics_lines.png)','', '| 任务（各 n=24） | 基线 | 改进版 | 口径 |','|---|---:|---:|---|']
 for task,label,key,desc in [('MTB/problem_solving','解题','native_score','源末尾数值解析'),('MTB/problem_solving','解题：最终标记诊断','tagged_answer_score','最后明确 Final Answer 后单数值'),('MTB/mistake_correction','纠错','native_score','源数值解析'),('MTB/mistake_correction','纠错：最终标记诊断','tagged_answer_score','覆盖率另列'),('MTB/solution_correctness','错误识别','native_score','源 Yes/No 兼容解析'),('MTB/solution_correctness','错误识别：严格格式','score','整段 Yes/No；无法解析计错'),('MTB/mistake_location','错误位置','native_score','源首个数字解析'),('MTB/mistake_location','错误位置：严格格式','score','整段为步骤编号'),('MTB/socratic_questioning','苏格拉底提问','score','BLEU 相似度，不是正确率')]:
  lines.append(f'| {label} | {pct(s["baseline"]["test"][task][key])} | {pct(s[candidate]["test"][task][key])} | {desc} |')
 lines += ['', 'BLEU 会受回答语言一致性影响，不据其提升幅度直接推断教学能力增幅。解题最终标记诊断没有提升，源解析大幅提升主要来自去掉回答后的无关基础练习。纠错最终标记诊断略降，完整报告保留这一下降；4 条由对变零的样本均为最终句含多个数值造成解析失败，可见回答结果正确，详见 `OBJECTIVE_ERROR_AUDIT.md`。不能据此断言数学退步，也不能把格式修复当成数学推理能力全面提高。','', '| 诊断覆盖率 | 基线 | 改进版 |','|---|---:|---:|']
 for task,label,key in [('MTB/problem_solving','解题最终标记可解析','tagged_answer_parsed'),('MTB/mistake_correction','纠错最终标记可解析','tagged_answer_parsed'),('MTB/solution_correctness','严格 Yes/No 可解析','parsed'),('MTB/mistake_location','严格步骤编号可解析','parsed')]:lines.append(f'| {label} | {pct(s["baseline"]["test"][task][key])} | {pct(s[candidate]["test"][task][key])} |')
 lines += ['', '## 教学回应质量与高中相关任务','', '| 任务 | n | 基线六项满足率 | 改进六项满足率 | 基线数学正确项 | 改进数学正确项 |','|---|---:|---:|---:|---:|---:|']
 for task in ['MTB/scaffolding_generation','MTB/pedagogy_following','MTB/scaffolding_generation_hard','MTB/pedagogy_following_hard','MathDial/next_turn','MRBench/next_turn','TutorBench/Calculus','TutorBench/Statistics']:
  a=s['baseline']['test'][task];b=s[candidate]['test'][task];lines.append(f'| {task} | {a["n"]} | {pct(a["quality"])} | {pct(b["quality"])} | {pct(a["criteria"]["math_correct"])} | {pct(b["criteria"]["math_correct"])} |')
 lines += ['', '六项分别为数学正确、回应学生、可执行性、指令遵循、披露适当、尊重语气；它们的均值不能叫作纯数学准确率。完整逐项结果见 `report/summary.json`。','', '| TutorBench 学科 | 基线加权 rubric | 改进加权 rubric |','|---|---:|---:|']
 for task in ['TutorBench/Calculus','TutorBench/Statistics']:
  lines.append(f'| {task.split("/")[-1]} | {pct(s["baseline"]["test"][task]["rubric_score"])} | {pct(s[candidate]["test"][task]["rubric_score"])} |')
 lines += ['', 'TutorBench 采用 critical=5、not_critical=1、critical_negative=-5；deleted 不计。负向项以“是否发生禁止行为”计命中，不截断负分。原论文使用 Sonnet 4，且包含多学科及图片，本轮数学文本子集与评审模型不同，不能直接对比原榜单。见 [TutorBench 论文](https://arxiv.org/abs/2510.02663)。','', '## 迭代记录','', '| 轮次 | 开发六项满足率（40 条） | 开发数学正确项 | TutorBench rubric（16 条） | 数值最终标记（16 条） | 采用情况 |','|---|---:|---:|---:|---:|---|']
 for run,values in choice['development'].items():
  state='基线' if run=='baseline' else '采纳并冻结' if run==candidate else '保留结果，未采纳'
  lines.append(f'| {run} | {pct(values["quality"])} | {pct(values["math_correct"])} | {pct(values["rubric"])} | {pct(values["tagged_numeric"])} | {state} |')
 lines += ['', '采纳的通用修改包括：跟随当前学生请求的语言；区分当前请求和嵌入的历史对话；防止英文 graph 名词误触发作图；成功回答后不再追加无关基础练习；加强检查学生完整结论和输出要求。产品提示中没有测试题 ID、参考答案或逐题 rubric。','', '第 3 轮加入输入算术预检及额外教学策略，整体分数下降，未并入采纳代码。其初版、边界修订版源码和输出均保留，不混合逐题最优回答。第 1 轮有 31+9 条分批评审，合并覆盖全部 40 条。','', '## 可靠性与失败','', '| 配置 | 原 312 条完成状态 |','|---|---|']
 for run,d in statuses.items():lines.append(f'| {run} | '+ '、'.join(f'{k}: {v}' for k,v in d.items())+' |')
 lines += ['', '主要分数把未完成和失败计为 0；原始状态与评审原分同时保留。`report/failures.csv` 列出所有自动零分、数学项失败与未完成项；不只挑选成功案例。','', '| 配对差值 | 平均变化 | 题组 bootstrap 95% 区间 |','|---|---:|---:|']
 for key,label in [('quality','教学六项满足率'),('rubric_score','TutorBench 加权 rubric'),('tagged_answer_score','数值最终标记诊断')]:
  d=pair[key];lo,hi=d['group_bootstrap_ci95'];lines.append(f'| {label} | {d["mean_difference"]*100:+.2f} 个百分点 | [{lo*100:+.2f}, {hi*100:+.2f}] |')
 lines += ['', '区间由固定种子进行 2,000 次题组重采样；它反映样本抽样不确定性，不覆盖单次生成随机性、评分器偏差或公开题库预训练污染。任务分层抽样也不代表中国各年级题目分布。','', '独立评审器在 6 个未用于被测生成的 MRBench 上下文、54 条原回应上校准：','', '| 人工标签维度 | 一致率 |','|---|---:|']
 for dim,d in cal.items():lines.append(f'| {dim} | {pct(d["agreement"])} |')
 lines += ['', 'MRBench 新回答的八维分类分布见 `report/mrbench_dimensions.csv`，均为模型评审，不移植原人类标签。语气、错误定位等维度一致性不足，模型评审必须作为辅助证据。MRBench 原人类标签不移植到我们的新回应。开发旋转体题的参考解已另用几何截面与 SymPy 积分复核，问题见 `REFERENCE_AUDIT.md`。部分参考解或标签存在可见性与数学问题，保留原金标准，评审器的 reference_caveat 另行保留；不通过改金标准抬分。','', '产品可能自主输出画布。本轮评审读取保留序列化图形块的文本载荷，未实际渲染或操作图形；这可能影响格式与人类化评分，不等同于界面交互评测。MathDial 本轮评测静态下一轮教师回应，没有模拟交互 Success@k，也不声称测得真实学习增益。MathTutorBench 的 question-rate 仅统计是否出现问句，其 100% 不等于教学质量 100%；原 Qwen 奖励模型未运行。公开源说明见 [MathDial](https://github.com/eth-nlped/mathdial)、[MathTutorBench](https://github.com/eth-lre/mathtutorbench) 和 [MRBench](https://github.com/kaushal0494/UnifyingAITutorEvaluation)。','', '## 资料、复现与后续优先项','', '协议、评分适配、异常和隔离决定分别见 `PROTOCOL.md`、`METHOD_NOTES.md`、`exclusions.json`。`freeze.json`、`data_manifest.json`、`source_manifest.json` 和源码快照用于核对来源。原 312 条敏感性结果保存在 `report/original_312_sensitivity.json`，主分析从未补题。','', '本次覆盖四个源仓库中的数学文本任务；TutorBench 原 1,473 条中数学文本 232 条，按学科固定抽样。图片、非数学题和没有实际运行的原生指标均单列，不声称完成四套全量官方基准。数据来源许可见 `ATTRIBUTION.md`。','', '后续优先处理高阶问题中的概念条件、学生误解识别与适量披露，并增加能独立核对的干净开发材料。当前测试集已解封，后续迭代需另封存新的测试题组；不得反复针对本批结果调参后继续称其为未见测试。','']
 (ROOT/'REPORT.md').write_text('\n'.join(lines))
 result={'primary_n':len(base),'quality_baseline':mean(bq,'quality'),'quality_candidate':mean(cq,'quality'),'tutorbench_baseline':mean(br,'rubric_score'),'tutorbench_candidate':mean(cr,'rubric_score'),'passed_all_development_guards':choice.get('passed_all_guards',False),'selected_run':candidate,'product_commit':commit,'statuses_original312':statuses}
 (ROOT/'report/headline.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
