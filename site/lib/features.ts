import type { Locale } from '@/lib/site';

export type FeatureStatus = 'implemented' | 'partial' | 'experimental' | 'planned';

export type Feature = {
  id: string;
  status: FeatureStatus;
  icon: 'shield' | 'messages' | 'clipboard' | 'repeat' | 'search' | 'image' | 'monitor';
  zh: { name: string; problem: string; how: string; visible: string; limits: string };
  en: { name: string; problem: string; how: string; visible: string; limits: string };
};

export const features: Feature[] = [
  {
    id: 'math-verification',
    status: 'implemented',
    icon: 'shield',
    zh: {
      name: '数学核验 Math Verification',
      problem: '通用聊天会把模型写出的步骤当成已经正确。',
      how: '受支持题型走本地 parser → solver → verifier。讲解中的算式经 verify_math 核对；有理系数一元多项式求导走精确局部核验。',
      visible: '可核验的结论标为已核对；无法解析或超出语法的推理标为未核验；被反驳的内容原处标出。',
      limits:
        '覆盖算术与分数、整式、一元一次/二次方程、二元一次方程组、一元一次不等式、根为有理数的一元二次不等式。证明题与超出语法的推理不会被假装成完整形式化证明。',
    },
    en: {
      name: 'Math Verification',
      problem: 'A general chatbot treats generated steps as if they were already correct.',
      how: 'Supported families go through a local parser, solver, and verifier. Expressions in explanations pass verify_math. Rational-coefficient univariate derivatives use a bounded exact checker.',
      visible: 'Checkable claims are marked verified. Unparseable or out-of-scope reasoning is unmarked. Refuted content stays visible in place.',
      limits:
        'Coverage is arithmetic and fractions, polynomials, linear/quadratic equations, 2×2 linear systems, linear inequalities, and quadratic inequalities with rational roots. Proofs and out-of-grammar reasoning are not presented as full formal proofs.',
    },
  },
  {
    id: 'socratic-guidance',
    status: 'implemented',
    icon: 'messages',
    zh: {
      name: '苏格拉底式分级引导',
      problem: '直接给完整答案会跳过学生自己的尝试。',
      how: '教学状态机驱动回合；SolutionDisclosureProjector 按 L0–L5 裁剪写作者可见的解。低等级在数据上就不含完整步骤。',
      visible: '提示、策略、下一步与完整解答分步出现。未解决题目需先看过提示才能看完整答案。',
      limits: '披露策略约束的是产品上下文，不是模型“自觉”。未配置模型时回退到本地模板教学。',
    },
    en: {
      name: 'Socratic Guidance',
      problem: 'Dumping the full answer skips the student’s own attempt.',
      how: 'A teaching state machine drives the turn. SolutionDisclosureProjector clips what the writer can see at L0–L5, so low levels structurally lack the full solution.',
      visible: 'Hints, strategy, the next step, and the full solution appear in order. Unsolved items require a hint before the full answer.',
      limits: 'Disclosure is a product context boundary, not model self-control. Without a configured model, tutoring falls back to local templates.',
    },
  },
  {
    id: 'learning-evidence',
    status: 'implemented',
    icon: 'clipboard',
    zh: {
      name: '学习证据 Learning Evidence',
      problem: '把“看过、收藏、说懂了”记成掌握，会高估学习。',
      how: 'LearningEvidence 只从服务端已提交的判题事实生成，追加写入、幂等去重。独立、受助、看答案后的作答分开统计。',
      visible: '学习画像、阶段复盘和导出列出有依据的作答与诊断出的错误概念。',
      limits: '未判定的作答不生成证据。插件输出、题库参考答案和自我报告不会自动写入掌握度。',
    },
    en: {
      name: 'Learning Evidence',
      problem: 'Counting views, bookmarks, or “I get it” as mastery inflates learning.',
      how: 'LearningEvidence is built only from server-committed assessments. Records are append-only and idempotent. Independent, assisted, and after-reveal attempts are stored separately.',
      visible: 'The learning profile, stage review, and export show attributable attempts and diagnosed misconceptions.',
      limits: 'Undetermined attempts yield no evidence. Plugin output, author keys, and self-reports do not become mastery.',
    },
  },
  {
    id: 'adaptive-practice',
    status: 'implemented',
    icon: 'repeat',
    zh: {
      name: '自适应练习 Adaptive Practice',
      problem: '下一题如果只靠模型出题，对错与难度都无法核验。',
      how: '候选练习必须经过解析、求解、验证和不可变发布门，才能变成 PracticeOffer。来源声明（题库/模板/LLM）不是信任授予。',
      visible: '完成教学循环后可收到练习邀请；学情中的错误概念可影响后续练习。',
      limits: 'DKT 最多把下一步或难度调节一档，且仅在技能可映射并存在独立作答时。高中未覆盖技能保持未知。',
    },
    en: {
      name: 'Adaptive Practice',
      problem: 'If the next item is only model-written, correctness and difficulty are unchecked.',
      how: 'Candidate exercises must pass parse, solve, verify, and an immutable release gate before they become a PracticeOffer. A BANK/TEMPLATE/LLM source label is a claim, not a trust grant.',
      visible: 'After a tutoring cycle the app can offer practice. Diagnosed misconceptions can affect later items.',
      limits: 'DKT may shift the next step or difficulty by at most one notch, and only for mapped skills with independent history. Unmapped high-school skills stay unknown.',
    },
  },
  {
    id: 'knowledge-retrieval',
    status: 'partial',
    icon: 'search',
    zh: {
      name: '知识检索 Knowledge Retrieval',
      problem: '把资料丢进提示词，无法证明回答来自哪一段原文。',
      how: '导入文本、Markdown 和可提取文字的 PDF，经切片、FTS 检索、权限过滤后组装。引用绑定资料版本与字符区间。',
      visible: '对话资料中选择参考范围，回答可回到原文。知识模式下模型只能调用应用授权的检索与读取工具。',
      limits: '默认是词法检索。向量检索需用户显式安装或配置 embedding，默认关闭。没有 OCR。扫描版 PDF 无法当作出题图片识别。',
    },
    en: {
      name: 'Knowledge Retrieval',
      problem: 'Pasting notes into a prompt cannot prove which span the answer used.',
      how: 'Text, Markdown, and text-extractable PDFs are chunked, searched with FTS, and filtered by permission. Citations bind a document version and character range.',
      visible: 'Conversation sources are chosen in “对话资料”. Answers can return to the original span. Knowledge-mode tools are application-authorized.',
      limits: 'Lexical search is the default. Vector search is opt-in and off by default. There is no OCR. Scanned PDFs are not treated as solved images.',
    },
  },
  {
    id: 'multimodal',
    status: 'partial',
    icon: 'image',
    zh: {
      name: '多模态交互 Multimodal Interaction',
      problem: '学生常常拍题，但把图片直接当成已核验作答并不安全。',
      how: '粘贴、选择或拖入 PNG/JPEG/WebP（每张 ≤10 MiB，每条最多 4 张）。仅当当前模型声明视觉能力时才把图片发给模型。',
      visible: '输入框上方显示缩略图。数形结合图形由应用计算坐标，前端绘制，而不是模型画字符图。',
      limits: 'OpenAI 清单内模型与声明 vision 的 Ollama 模型可用。DeepSeek、Moonshot、Custom 当前未确认视觉能力。图片讨论不记作掌握证据，也没有 OCR 引擎。',
    },
    en: {
      name: 'Multimodal Interaction',
      problem: 'Students photograph problems, but an image is not a verified attempt.',
      how: 'Paste, pick, or drop PNG/JPEG/WebP (≤10 MiB, 4 per message). Images reach the model only when that model reports vision.',
      visible: 'Thumbnails sit above the composer. Graphs are computed by the app and drawn on canvas, not as ASCII art.',
      limits: 'Listed OpenAI vision models and Ollama models that advertise vision work. DeepSeek, Moonshot, and Custom currently do not. Image chat is not mastery evidence, and there is no OCR engine.',
    },
  },
  {
    id: 'desktop',
    status: 'implemented',
    icon: 'monitor',
    zh: {
      name: '本地优先桌面应用',
      problem: '浏览器演示无法长期保存密钥、资料和学习记录。',
      how: 'Electron 启动本机 Python 服务、Verifier Worker 与前端。API Key 进系统钥匙串/凭据管理器。可选 SQLCipher 整库加密。',
      visible: 'Windows x64 EXE 与 macOS arm64 DMG（0.7.0 r3）。安装包内置 Python/Node，不必另装开发环境。',
      limits: '安装包未使用发行证书签名；Mac 未公证。Linux 没有经过目标机验证的公开发布包。使用云端模型时，题目与上下文会发送给所配置的服务商。',
    },
    en: {
      name: 'Local-first Desktop Application',
      problem: 'A browser demo cannot keep keys, notes, and learning history for the long run.',
      how: 'Electron launches a local Python service, verifier worker, and UI. API keys go to the OS credential store. SQLCipher whole-database encryption is optional.',
      visible: 'Windows x64 EXE and macOS arm64 DMG (0.7.0 r3). Installers bundle Python/Node, so users do not install a toolchain.',
      limits: 'Installers are not release-certificate signed; macOS is not notarized. Linux has no target-machine-verified public package. Cloud models receive the problem and context you send them.',
    },
  },
];

export function featureCopy(feature: Feature, locale: Locale) {
  return locale === 'zh' ? feature.zh : feature.en;
}

export const statusLabel: Record<Locale, Record<FeatureStatus, string>> = {
  zh: {
    implemented: '已实现',
    partial: '部分实现',
    experimental: '实验性',
    planned: '规划中',
  },
  en: {
    implemented: 'Implemented',
    partial: 'Partial',
    experimental: 'Experimental',
    planned: 'Planned',
  },
};
