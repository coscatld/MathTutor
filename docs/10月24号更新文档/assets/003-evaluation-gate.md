# MT-EVAL-002：零场景与子集评测门禁

日期：2026-10-24（Asia/Shanghai）。基线：`4e713f93322c967cd11fa1f0c26f3a91b291fb02`。

## 缺陷与修复

在原代码上新增回归后，9项失败：`score([])`返回通过，未知ID被静默忽略、混合选择仍执行已知项、空`--only`会回退全套，CLI可返回0且报告没有覆盖范围。

实际修改：

- `src/mathtutor/evaluation/tutor_multiturn.py`：零场景及完全没有执行检查的场景硬失败；选择ID在创建数据库、产品会话或调用模型前统一校验；完整套件和子集记录实际执行ID、遗漏ID及覆盖数。
- `scripts/tutor_multiturn_eval.py`：`--only`至少提供一个ID；非法选择退出2；已执行检查失败退出1；合法子集检查通过允许退出0。
- JSON新增`coverage`及`release_gate.passed`。`gate.passed`继续表示已执行检查结果；完整套件且检查通过才允许`release_gate.passed=true`。Markdown子集明确显示“子集回归通过”“全套发布门未验收”。
- `tests/test_tutor_multiturn_eval.py`：纯评分负例、调用前拒绝、真实CLI子进程选择验证、合法子集、完整产品WebSocket评测和既有错误模型/失败终态回归。
- `docs/eval/TUTOR_MULTITURN_EVAL.md`：记录机器消费字段与退出码，修正文档中套件场景数为实际16项。历史评测结果保留时间，不倒改为本轮结果。

## 验证

命令：`PYTHONPATH=src <DEV_PYTHON> -m pytest tests/test_tutor_multiturn_eval.py -q --tb=short`。

修复后整文件：**14 passed、241 warnings，10.03秒**。首轮绿测有1项测试对argparse原生空参数报错文案的断言不匹配，已改为准确断言`--only: expected at least one argument`，保留退出2和不生成报告的断言；这不是忽略失败。

另经真实模板CLI运行固定套件，初次全套 **16/16**、六维1.0、发布门通过；这是本机无模型、临时数据库的自动工程回归，最终合并代码的全量验收见003主报告。未用API Key、训练或调用付费模型。日志已保存至本机临时目录，主报告归档最终结果。

## 依据与适用边界

[Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)，2026-01-09，Anthropic官方工程实践文章，非同行评审教育效果实验。其方法将任务、检查器、完整轨迹与最终环境状态分别记录，强调基于真实失败构造可复现回归。MathTutor已有WebSocket驱动和六维规则，本轮补齐选择与覆盖门槛；没有采用新评测框架或LLM评分器。这只能修复验收可信度，不能证明学生学习收益。

[pytest退出码规范](https://docs.pytest.org/en/stable/reference/exit-codes.html)，官方工程文档（访问2026-10-24），将未收集到测试与成功明确区分。本轮沿用这个语义，CLI具体使用已有失败码1/参数码2，不要求与pytest数字完全相同。

无新依赖、外部服务、学生数据迁移或正常推理延迟开销。依赖旧`gate.passed`判断全套发布的外部脚本应迁移到`release_gate.passed`；旧报告没有这个字段时不能默认通过。本仓库未发现其他消费该字段的发布脚本。合法有意子集仍能用于开发回归。

## 合并后的评测契约

学习归因修复后，两条旧场景仍期望技能误归因；第一次合并探测为33通过、2失败。保留场景与门槛，改为严格检查整题错误规则、精确相关技能、纠正状态、原错误来源和纠正事件，并要求活动技能误概念为空；这些检查标为critical。增加4种坏画像负例，确保丢观察、错误技能归因、伪纠正和技能不匹配不能通过。缺coverage的旧报告重渲染也显示全套未验收。随后合并相关49项通过。最终全套模板CLI已16/16通过，六维得分均1.0，学生证据19/19；参见[完整报告](003-multiturn-template.md)和[JSON轨迹](003-multiturn-template.json)。最终源代码全量检查见主报告。
