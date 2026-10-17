import type { Locale } from '@/lib/site';

export type RoadmapStatus = 'completed' | 'in-progress' | 'planned';

export const roadmap: {
  status: RoadmapStatus;
  zh: string;
  en: string;
}[] = [
  {
    status: 'completed',
    zh: '受支持题型的确定性求解与 verify_math；L0–L5 分级披露与教学状态机。',
    en: 'Deterministic solving and verify_math for supported families; L0–L5 disclosure and the teaching state machine.',
  },
  {
    status: 'completed',
    zh: '独立 / 受助 / 看答案后作答证据、学习画像与练习发布门。',
    en: 'Independent / assisted / after-reveal evidence, learning profiles, and the practice release gate.',
  },
  {
    status: 'completed',
    zh: '本地资料 FTS 检索、引用区间、知识库编辑与对话资料选择。',
    en: 'Local FTS retrieval, citation spans, knowledge-base editing, and conversation source selection.',
  },
  {
    status: 'completed',
    zh: '数形结合画布、图片附件（有视觉能力时）、社区插件与斜杠命令。',
    en: 'Canvas graphs, image attachments when the model has vision, community plugins, and slash commands.',
  },
  {
    status: 'completed',
    zh: 'Windows x64 与 macOS arm64 0.7.0 r3 安装包及跨平台源码 CI。',
    en: 'Windows x64 and macOS arm64 0.7.0 r3 installers, plus cross-platform source CI.',
  },
  {
    status: 'in-progress',
    zh: 'DKT 仅在可映射技能上最多调节一档；真实学生数据上的效果仍未验证。',
    en: 'DKT may shift one notch on mapped skills; learning-effect validation on real MathTutor students is still open.',
  },
  {
    status: 'in-progress',
    zh: 'Embedding / 向量检索为用户显式 opt-in，默认词法检索。',
    en: 'Embedding / vector search is explicit opt-in; lexical search remains the default.',
  },
  {
    status: 'in-progress',
    zh: '扩展数学核验覆盖范围（更多不等式、函数与证明边界的诚实标注）。',
    en: 'Widen math verification coverage, with honest labels for functions, inequalities, and proofs outside the grammar.',
  },
  {
    status: 'planned',
    zh: 'GitHub 开源资源索引、插件版本管理与社区贡献审核（见 COMMUNITY_ROADMAP）。',
    en: 'A GitHub resource catalog, plugin versioning, and contribution review (see COMMUNITY_ROADMAP).',
  },
  {
    status: 'planned',
    zh: '教师协同试点；不以当前基准分数宣称课堂效果。',
    en: 'Teacher-collaboration pilots, without treating current benchmarks as classroom outcomes.',
  },
  {
    status: 'planned',
    zh: 'Linux 目标机验收与公开发布包；发行证书签名与 macOS 公证。',
    en: 'Linux target-machine verification and a public package; release-certificate signing and macOS notarization.',
  },
  {
    status: 'planned',
    zh: '国际化界面与文档社区建设（本站点是其中一步）。',
    en: 'Product UI internationalization and community docs (this site is one step).',
  },
];

export function roadmapGroups(locale: Locale) {
  const pick = (item: (typeof roadmap)[number]) => (locale === 'zh' ? item.zh : item.en);
  return {
    completed: roadmap.filter((i) => i.status === 'completed').map(pick),
    inProgress: roadmap.filter((i) => i.status === 'in-progress').map(pick),
    planned: roadmap.filter((i) => i.status === 'planned').map(pick),
  };
}
