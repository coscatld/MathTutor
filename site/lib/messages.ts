import type { Locale } from '@/lib/site';

export const messages = {
  zh: {
    htmlLang: 'zh-CN',
    localeName: '简体中文',
    otherLocale: 'en' as Locale,
    otherLocaleName: 'English',
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
    langSwitch: '切换语言',
    search: '搜索文档',
    hero: {
      eyebrow: '开源数学智能辅导系统 · 0.7.0',
      title: '数迹 MathTutor——不止于解答，更关注真正掌握。',
      subtitle:
        '可验证的数学推理、分级教学引导、学习过程追踪、独立迁移验证，以及开源与本地优先的桌面应用。模型负责表达，应用负责权限、证据、答案披露与数据边界。',
      getStarted: '开始使用',
      documentation: '阅读文档',
      download: '下载安装包',
      github: 'GitHub',
    },
    loopTitle: '四阶段教学闭环',
    loop: [
      { title: '独立尝试', body: '学生先作答。未解决的题目要先看过一次提示，才能查看完整答案。' },
      { title: '分级引导', body: 'L0–L5 披露边界由产品控制：概念提示、策略、下一步，直到完整核验解。' },
      { title: '迁移验证', body: '练习题经同一套解析—求解—验证门发布，不把作者参考答案当成已核验事实。' },
      { title: '学情更新', body: '独立、受助、看答案后的作答分开记账；阅读或一句“懂了”只作为自我报告。' },
    ],
    whyTitle: '为什么是 MathTutor',
    why: [
      { title: '可验证数学推理', body: '受支持题型由本地求解器与验证器处理，讲解中的算式经 verify_math 核对。' },
      { title: '分级教学引导', body: '低提示等级的表达层看不到完整答案，模型措辞可以变化，披露边界仍由产品控制。' },
      { title: '学习过程追踪', body: '作答证据追加写入，删除证据会更新画像投影，不把自我报告写成掌握度。' },
      { title: '独立迁移验证', body: '练习发布走同一验证门；LLM 不参与核验权威。' },
      { title: '开源与本地优先', body: '数据在本机 SQLite 与系统凭据库中。未配置云端模型时，本地求解、验证与模板教学仍可用。' },
    ],
    screenshotCaption: '真实 0.7.x 产品界面截图，不是示意稿。',
    ctaTitle: '从安装包或源码开始',
    ctaBody: 'Windows x64 与 macOS Apple Silicon 提供 0.7.0 r3 安装包。开发者可按文档在本地运行 Python 服务与 Next.js 工作台。',
    footer: {
      license: 'Apache-2.0',
      deeptutor: '在 DeepTutor 基础上二次开发，保留上游 Apache-2.0 与 HKU Data Intelligence Lab 版权声明。',
      notLive: '官网托管在 GitHub Pages。',
    },
    featuresPage: {
      title: '功能与边界',
      intro: '每一项都对应仓库中的实现与文档。状态分为已实现、部分实现、实验性与规划中，不把测试通过写成真实教学验证。',
    },
    downloadPage: {
      title: '下载 MathTutor',
      intro: '当前正式版本 0.7.0。请使用修复普通数学提问与讨论题教学按钮的 r3 安装包。',
      notes: '安装说明',
      releases: 'GitHub Releases',
      macGuide: 'macOS 安装说明',
      linuxTitle: 'Linux',
      unsignedTitle: '签名与公证状态',
      unsignedBody:
        '两个当前安装包都没有发行证书签名。Mac r3 为本地 ad-hoc 签名且未公证；Windows 可能出现 SmartScreen。这不代表安装包未构建或未做启动验收。',
    },
    architecturePage: {
      title: '系统架构',
      intro: '学生界面、教学状态、数学核验、学习证据、学生模型与练习推荐分开。LLM 负责语言表达，不负责在支持范围外证明数学正确。',
    },
    roadmapPage: {
      title: '路线图',
      intro: '状态与仓库当前研发一致。完成项来自已发布的 0.7.0；进行中与规划来自社区路线图与学生模型文档。',
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
    chooseLanguage: '选择语言',
  },
  en: {
    htmlLang: 'en',
    localeName: 'English',
    otherLocale: 'zh' as Locale,
    otherLocaleName: '简体中文',
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
    langSwitch: 'Switch language',
    search: 'Search docs',
    hero: {
      eyebrow: 'Open-source math tutoring · 0.7.0',
      title: 'MathTutor — Beyond Answers, Toward Real Understanding.',
      subtitle:
        'Verifiable math reasoning, graded Socratic guidance, learning-process evidence, independent transfer practice, and a local-first open-source desktop app. The model writes; the product owns permissions, evidence, answer disclosure, and data boundaries.',
      getStarted: 'Get Started',
      documentation: 'Documentation',
      download: 'Download',
      github: 'GitHub',
    },
    loopTitle: 'A four-stage tutoring loop',
    loop: [
      { title: 'Independent attempt', body: 'Students try first. Unsolved items require seeing a hint before the full answer.' },
      { title: 'Graded guidance', body: 'L0–L5 disclosure is a product boundary: concept, strategy, next step, then the verified solution.' },
      { title: 'Transfer check', body: 'Practice items pass the same parse–solve–verify gate. Author keys are not treated as verified facts.' },
      { title: 'Evidence update', body: 'Independent, assisted, and after-reveal attempts are counted separately. “I get it” is only a self-report.' },
    ],
    whyTitle: 'Why MathTutor',
    why: [
      { title: 'Verifiable math', body: 'Supported families are solved and checked locally. Expressions in explanations go through verify_math.' },
      { title: 'Graded teaching', body: 'Low hint levels never receive the full solution. Wording may vary; disclosure does not.' },
      { title: 'Learning evidence', body: 'Trusted attempts are append-only. Deleting evidence updates the profile. Self-reports are not mastery.' },
      { title: 'Independent transfer', body: 'Released exercises share one verification gate. The LLM is not the verifier of record.' },
      { title: 'Open source, local-first', body: 'Data stays in local SQLite and the OS credential store. Local solve, verify, and template tutoring work without a cloud model.' },
    ],
    screenshotCaption: 'Screenshots from the real 0.7.x app, not mockups.',
    ctaTitle: 'Start from an installer or from source',
    ctaBody: '0.7.0 r3 installers are published for Windows x64 and macOS Apple Silicon. Developers can run the Python service and Next.js workbench locally.',
    footer: {
      license: 'Apache-2.0',
      deeptutor: 'Derived from DeepTutor. Upstream Apache-2.0 and the HKU Data Intelligence Lab copyright notice are preserved.',
      notLive: 'The website is hosted on GitHub Pages.',
    },
    featuresPage: {
      title: 'Features and limits',
      intro: 'Every item maps to code and docs in the repository. Status is implemented, partial, experimental, or planned. Passing tests is not classroom validation.',
    },
    downloadPage: {
      title: 'Download MathTutor',
      intro: 'Current release: 0.7.0. Use the r3 installers, which fix ordinary math questions and enable teaching help for saved discussions.',
      notes: 'Install notes',
      releases: 'GitHub Releases',
      macGuide: 'macOS install guide',
      linuxTitle: 'Linux',
      unsignedTitle: 'Signing status',
      unsignedBody:
        'Neither current installer uses a release certificate. The Mac r3 build is locally ad-hoc signed and not notarized; Windows may show SmartScreen. That is separate from build and launch verification.',
    },
    architecturePage: {
      title: 'Architecture',
      intro: 'Student UI, teaching state, math verification, learning evidence, the student model, and practice recommendation are separate. The LLM owns language, not unsupported mathematical proof.',
    },
    roadmapPage: {
      title: 'Roadmap',
      intro: 'Aligned with the current repository. Completed items shipped in 0.7.0. In-progress and planned items come from the community roadmap and student-model docs.',
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
    chooseLanguage: 'Choose a language',
  },
} as const;

export type Messages = (typeof messages)[Locale];

export function t(locale: Locale): Messages {
  return messages[locale];
}
