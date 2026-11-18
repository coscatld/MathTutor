import type { Locale } from '@/lib/site';

export const messages = {
  zh: {
    htmlLang: 'zh-CN',
    localeName: '简体中文',
    skip: '跳到主要内容',
    nav: {
      home: '首页',
      features: '功能',
      download: '下载',
      architecture: '架构',
      roadmap: '路线图',
      docs: '文档',
      github: 'GitHub',
    },
    theme: { light: '浅色', dark: '深色', system: '跟随系统', toggle: '切换颜色主题' },
    search: '搜索文档',
    hero: {
      eyebrow: '桌面 AI 数学学习与知识探索',
      title: '让每一步推理，都有迹可循。',
      subtitle:
        '从自己尝试一道题开始，在需要时获得提示，再用一道新题检验理解。也可以带着疑问探索不同解释，把资料来源、自己的思考和下一步练习连起来。',
      getStarted: '第一次使用',
      download: '下载安装包',
      github: 'GitHub',
    },
    loopTitle: '一道题怎样学完',
    loop: [
      { title: '独立尝试', body: '先写下你的答案或第一步。应用会核对支持题型的计算结果。' },
      { title: '按需看提示', body: '从一个概念或一个问题开始，走不下去时再看下一步。' },
      { title: '换题再试', body: '完成后接一道相关练习，检查换个条件还能否独立解出。' },
      { title: '回看学习记录', body: '区分自己完成、获得帮助和看过答案的题，找到下次要练的地方。' },
    ],
    whyTitle: '你能带走什么',
    why: [
      { title: '能核对的推理', body: '基础算式、方程和不等式可以在本机核验。题意不清时，应用会请你补充条件。' },
      { title: '适合当下的提示', body: '卡在哪一步就从哪一步继续，可以选择看提示、例子或解答。' },
      { title: '看得懂的学习记录', body: '回看作答、用过的提示和新题表现，了解一次练习告诉了你什么。' },
      { title: '有依据的学习计划', body: '带上自己的目标和时间，结合作答与前置知识安排下一步。' },
      { title: '离线也能学习', body: '基础练习、分级提示和本地学习记录可以离线使用。需要外部资料时再开启联网。' },
    ],
    screenshotCaption: '桌面应用中的参考资料和课程题库。',
    ctaTitle: '在桌面上开始第一道题',
    ctaBody: '下载适合你电脑的安装包，打开 MathTutor，即可开始练习。',
    footer: {
      license: 'Apache-2.0',
      deeptutor: '在 DeepTutor 基础上二次开发，保留上游 Apache-2.0 与 HKU Data Intelligence Lab 版权声明。',
    },
    featuresPage: {
      title: '功能与边界',
      intro: '查看数学辅导、学习记录和知乎知识探索能怎样帮助你，以及哪些结果可以核验。',
    },
    downloadPage: {
      title: '下载 MathTutor',
      intro: '选择适合你电脑的安装包。安装后即可练习数学、查看学习记录，并按需连接知乎探索资料。',
      notes: '安装说明',
      releases: 'GitHub Releases',
      unsignedTitle: '签名与公证状态',
      unsignedBody:
        '两个当前安装包都没有发行证书签名。Mac 为完整本地 ad-hoc 签名且未公证，首次打开需明确允许；Windows 可能出现 SmartScreen。安装验收记录见发布页。',
    },
    architecturePage: {
      title: '系统架构',
      intro: '学生界面、教学状态、数学核验、学习证据、学生模型与练习推荐分开。LLM 负责语言表达，不负责在支持范围外证明数学正确。',
    },
    roadmapPage: {
      title: '路线图',
      intro: '了解当前可用的学习工具，以及接下来准备扩展的能力。',
      completed: '已完成',
      inProgress: '进行中',
      planned: '规划中',
    },
    notFound: {
      title: '没有找到这个页面',
      body: '链接可能写错，或该语言下没有对应文档。',
      home: '回到首页',
      docs: '打开文档',
    },
  },
  en: {
    htmlLang: 'en',
    localeName: 'English',
    skip: 'Skip to main content',
    nav: {
      home: 'Home',
      features: 'Features',
      download: 'Download',
      architecture: 'Architecture',
      roadmap: 'Roadmap',
      docs: 'Docs',
      github: 'GitHub',
    },
    theme: { light: 'Light', dark: 'Dark', system: 'System', toggle: 'Toggle color theme' },
    search: 'Search docs',
    hero: {
      eyebrow: 'Desktop AI math learning and knowledge exploration',
      title: 'A clear path through every step of your reasoning.',
      subtitle:
        'Try a problem, ask for a hint, and check your understanding on a new one. Or follow a question into different explanations, connecting their sources with your own reflection and next practice.',
      getStarted: 'First steps',
      download: 'Download',
      github: 'GitHub',
    },
    loopTitle: 'Work through a problem',
    loop: [
      { title: 'Try independently', body: 'Write an answer or a first step. MathTutor checks the calculation for supported problems.' },
      { title: 'Ask for a hint', body: 'Start with a concept or a question, then reveal another step if you need it.' },
      { title: 'Try a new problem', body: 'Change the numbers or conditions and check whether you can solve the new problem independently.' },
      { title: 'Review your work', body: 'See which problems you solved on your own, where a hint helped, and what to revisit.' },
    ],
    whyTitle: 'What you can learn from a session',
    why: [
      { title: 'Reasoning you can check', body: 'Basic expressions, equations and inequalities can be checked locally. If information is missing, the tutor asks for it.' },
      { title: 'Help at the point you need it', body: 'Choose a hint, an example or a worked solution as you work through a problem.' },
      { title: 'A record of how you learned', body: 'Review attempts, hints and independent practice together to see how you solved each problem.' },
      { title: 'A plan built around your goal', body: 'Choose a goal and a time limit. Your attempts and prerequisite skills help shape the next step.' },
      { title: 'Practice offline', body: 'Local math practice, guided hints and learning records work offline. Enable online search when you want outside sources.' },
    ],
    screenshotCaption: 'Reference materials and the course question bank in the desktop app.',
    ctaTitle: 'Try your first problem on desktop',
    ctaBody: 'Choose the installer for your computer, open MathTutor and start a practice session.',
    footer: {
      license: 'Apache-2.0',
      deeptutor: 'Derived from DeepTutor. Upstream Apache-2.0 and the HKU Data Intelligence Lab copyright notice are preserved.',
    },
    featuresPage: {
      title: 'Features and limits',
      intro: 'Explore math tutoring, learning records and Zhihu research, including what the app can check.',
    },
    downloadPage: {
      title: 'Download MathTutor',
      intro: 'Choose the installer for your computer. Practice math, review your progress and connect Zhihu when you want to explore a question.',
      notes: 'Install notes',
      releases: 'GitHub Releases',
      unsignedTitle: 'Signing status',
      unsignedBody:
        'Neither current installer uses a release certificate. The Mac build is fully ad-hoc signed locally and not notarized; first launch requires explicit approval. Windows may show SmartScreen. See the release page for installer acceptance records.',
    },
    architecturePage: {
      title: 'Architecture',
      intro: 'Student UI, teaching state, math verification, learning evidence, the student model, and practice recommendation are separate. The LLM owns language, not unsupported mathematical proof.',
    },
    roadmapPage: {
      title: 'Roadmap',
      intro: 'See what you can use today and what is being developed.',
      completed: 'Completed',
      inProgress: 'In progress',
      planned: 'Planned',
    },
    notFound: {
      title: 'Page not found',
      body: 'The URL may be wrong, or this locale has no matching document.',
      home: 'Back home',
      docs: 'Open docs',
    },
  },
} as const;

export type Messages = (typeof messages)[Locale];

export function t(locale: Locale): Messages {
  return messages[locale];
}
