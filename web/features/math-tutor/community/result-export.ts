import {translate, type MessageParams} from "@/lib/i18n/messages";
type Translator = (message: string, params?: MessageParams) => string;
const chinese: Translator = (message, params) => translate("zh-CN", message, params);
import type { ExamData, MistakeData, RunResult, TrendData } from "./api";

export const resultName = (result: RunResult, t: Translator = chinese) => ({"exam-builder": t("练习题"), "mistake-review": t("错题复盘"), "learning-report": t("学习趋势"), code: t("插件运行结果")})[result.workflow];

export function resultText(result: RunResult, t: Translator = chinese) {
  const lines = [resultName(result, t), "", result.workflow === "code" ? t("这是本机代码实际返回的内容，未据此确认数学正确或知识掌握。") : t("本次结果仅供参考，不会修改成绩或学习掌握情况。"), ""];
  if (result.workflow === "code") {
    lines.push(typeof result.data.text === "string" ? result.data.text : t("插件没有返回文字。"));
    const {text: _text, ...values} = result.data;
    if (Object.keys(values).length) lines.push("", JSON.stringify(values, null, 2));
  } else if (result.status === "empty") lines.push(result.workflow === "exam-builder" ? t("没有符合条件的题目，可以换个年级或先补充题库。") : t("还没有足够的实际记录，没有生成成绩或示例数据。"));
  else if (result.workflow === "exam-builder") {
    const data = result.data as unknown as ExamData;
    lines.push(data.title, t("已选 {value0} / 请求 {value1} 道", { value0: data.actual_count, value1: data.requested_count }), "");
    data.questions.forEach((question, index) => {
      lines.push(`${index + 1}. ${question.text}`, t("{value0} 年级 · {value1}", { value0: question.grade, value1: question.point_title }));
      if (data.answers_included && question.reference_answer) lines.push(t("参考答案：{value0}", { value0: question.reference_answer }), question.explanation || "");
      lines.push("");
    });
  } else if (result.workflow === "mistake-review") {
    const data = result.data as unknown as MistakeData;
    lines.push(t("核验记录 {value0} 条，符合复盘条件 {value1} 条，本次展示 {value2} 条。", { value0: data.assessed_count, value1: data.review_count, value2: data.items.length }), "");
    data.items.forEach((item, index) => lines.push(t("{value0}. {value1}", { value0: index + 1, value1: item.problem_text || t("未保留原题") }), t("当时的作答：{value0}", { value0: item.student_response || t("未保留文字作答") }), t("下一步：{value0}", { value0: item.next_step }), ""));
  } else {
    const data = result.data as unknown as TrendData, summary = data.summary;
    lines.push(t("独立作答：{value0} 次", { value0: summary.independent_attempts }), t("独立正确率：{value0}", { value0: summary.independent_accuracy === null ? t("暂无") : `${(summary.independent_accuracy * 100).toFixed(1)}%` }), t("获得帮助：{value0} 次", { value0: summary.assisted_attempts }), "");
    data.trend.forEach(row => lines.push(t("第 {value0} 组：{value1} / {value2} 正确，正确率 {value3}%", { value0: row.index, value1: row.correct, value2: row.attempts, value3: (row.accuracy * 100).toFixed(1) })));
    data.skills.forEach(skill => lines.push(t("{value0}：独立正确 {value1}、错误 {value2}；帮助后正确 {value3}、错误 {value4}", { value0: skill.label, value1: skill.independent_correct, value2: skill.independent_incorrect, value3: skill.assisted_correct, value4: skill.assisted_incorrect })));
    lines.push("", t("本次包含 {value0} 条记录{value1}。", { value0: data.window.included_events, value1: data.window.truncated ? t("，已达到所选记录范围上限") : "" }));
  }
  if (result.teaching_guidance) lines.push("", result.teaching_guidance);
  return lines.join("\n") + "\n";
}

export function saveResult(result: RunResult, t: Translator = chinese) {
  const link = document.createElement("a"), url = URL.createObjectURL(new Blob([resultText(result, t)], {type: "text/plain;charset=utf-8"}));
  link.href = url; link.download = `${resultName(result, t)}.txt`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
