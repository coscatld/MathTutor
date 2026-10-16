# 数据与代码来源

保留源仓库及下载文件，不将外部题库作为原创内容。精确版本及远端 URL 见 `source_manifest.json`，下载文件有 SHA-256 及来源 URL。本文档不是对上游许可证的替换。

| 材料 | 来源 | 许可与处理 |
|---|---|---|
| MathTutorBench | https://github.com/eth-lre/mathtutorbench | README 顶部写 CC BY 4.0，末尾正文写 CC BY-SA 4.0；记录这一冲突，保留原文。衍生题库中含 MathDial/Bridge 材料，不据顶部徽章放宽共享义务。 |
| MathDial | https://github.com/eth-nlped/mathdial | CC BY-SA 4.0，衍生对话样本沿用来源署名及相同许可。 |
| MRBench | https://github.com/kaushal0494/UnifyingAITutorEvaluation | CC BY-SA 4.0，原数据来自 MathDial 和 Bridge。人工标签只用于原回应校准。 |
| TutorBench | https://huggingface.co/datasets/ScaleAI/TutorBench | 当前本地数据卡未列明确 license 字段；保留原卡及原作者署名，本地研究评测不等同于已取得重新授权发布原数据的许可。 |
| StepVerify | https://huggingface.co/datasets/eth-nlped/stepverify | 上游 MathTutorBench 指定依赖；保留 Hugging Face 下载来源与摘要。 |
| GSM8K | https://huggingface.co/datasets/openai/gsm8k | 上游 MathTutorBench 指定依赖；原始 GSM8K 项目 https://github.com/openai/grade-school-math 使用 MIT。 |

引用论文：

- MathTutorBench: https://arxiv.org/abs/2502.18940
- Unifying AI Tutor Evaluation: https://aclanthology.org/2025.naacl-long.57/
- MathDial: https://aclanthology.org/2023.findings-emnlp.372/
- TutorBench: https://arxiv.org/abs/2510.02663

新编写的评测脚本沿用 MathTutor 的 Apache-2.0（见 LICENSE-CODE）；原题、原参考答案、rubric、人工标签及其衍生数据保留各自源许可。产品源码快照沿用 MathTutor 仓库的许可。未经明确授权，不把本地完整材料自动上传到新的公开数据集。
