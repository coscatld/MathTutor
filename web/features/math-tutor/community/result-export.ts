import type { ExamData, MistakeData, RunResult, TrendData } from "./api";

export const resultName = (result: RunResult) => ({"exam-builder": "练习题", "mistake-review": "错题复盘", "learning-report": "学习趋势"})[result.workflow];

export function resultText(result: RunResult) {
  const lines = [resultName(result), "", "本次结果仅供参考，不会修改成绩或学习掌握情况。", ""];
  if (result.status === "empty") lines.push(result.workflow === "exam-builder" ? "没有符合条件的题目，可以换个年级或先补充题库。" : "还没有足够的实际记录，没有生成成绩或示例数据。");
  else if (result.workflow === "exam-builder") {
    const data = result.data as unknown as ExamData;
    lines.push(data.title, `已选 ${data.actual_count} / 请求 ${data.requested_count} 道`, "");
    data.questions.forEach((question, index) => {
      lines.push(`${index + 1}. ${question.text}`, `${question.grade} 年级 · ${question.point_title}`);
      if (data.answers_included && question.reference_answer) lines.push(`参考答案：${question.reference_answer}`, question.explanation || "");
      lines.push("");
    });
  } else if (result.workflow === "mistake-review") {
    const data = result.data as unknown as MistakeData;
    lines.push(`核验记录 ${data.assessed_count} 条，符合复盘条件 ${data.review_count} 条，本次展示 ${data.items.length} 条。`, "");
    data.items.forEach((item, index) => lines.push(`${index + 1}. ${item.problem_text || "未保留原题"}`, `当时的作答：${item.student_response || "未保留文字作答"}`, `下一步：${item.next_step}`, ""));
  } else {
    const data = result.data as unknown as TrendData, summary = data.summary;
    lines.push(`独立作答：${summary.independent_attempts} 次`, `独立正确率：${summary.independent_accuracy === null ? "暂无" : `${(summary.independent_accuracy * 100).toFixed(1)}%`}`, `获得帮助：${summary.assisted_attempts} 次`, "");
    data.trend.forEach(row => lines.push(`第 ${row.index} 组：${row.correct} / ${row.attempts} 正确，正确率 ${(row.accuracy * 100).toFixed(1)}%`));
    data.skills.forEach(skill => lines.push(`${skill.label}：独立正确 ${skill.independent_correct}、错误 ${skill.independent_incorrect}；帮助后正确 ${skill.assisted_correct}、错误 ${skill.assisted_incorrect}`));
    lines.push("", `本次包含 ${data.window.included_events} 条记录${data.window.truncated ? "，已达到所选记录范围上限" : ""}。`);
  }
  if (result.teaching_guidance) lines.push("", result.teaching_guidance);
  return lines.join("\n") + "\n";
}

export function saveResult(result: RunResult) {
  const link = document.createElement("a"), url = URL.createObjectURL(new Blob([resultText(result)], {type: "text/plain;charset=utf-8"}));
  link.href = url; link.download = `${resultName(result)}.txt`; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
