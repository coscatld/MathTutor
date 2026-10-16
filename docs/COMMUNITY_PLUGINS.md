# 社区教学插件

普通用户可在社区一键导入插件，或选择已经下载的文件，再调整设置、启用、停用、导出和卸载。开发者编写与打包的完整步骤见[插件开发者指南](PLUGIN_DEVELOPMENT.md)。技术上，社区插件是经过严格校验的声明式数据包。插件把应用已有的安全工作流与作者的教学指导、有界默认配置组合成可分享的功能。它不携带可执行 Python、JavaScript、shell、import 路径或自动安装依赖。

这套机制与可信开发者的 [Python 扩展 SDK](CREATOR_EXTENSIONS.md) 分开：社区包是数据，实际处理器由 MathTutor 内置。作者不能通过说明文字获得新工具、目录权限或学生掌握状态的写权限。

## 安装与升级

1. 查看来源、作者、版本、许可、README、更新说明及需要的数据权限。
2. 点击资源卡片“导入”，或选择下载的 `.mathtutor` / `.mtplugin` 文件；**导入后默认停用**。
3. 阅读需要的数据权限，点“同意并启用”。
4. 调整设置后运行，点“保存结果”取得可阅读的文本。也可在对话中明确要求运行已启用插件。

同一包的重复安装是幂等操作。升级必须提高版本号，不能在同版本悄悄替换内容，也不能把同一插件 ID 改成另一种工作流。升级保留用户已有配置，并再次停用；新增权限不会自动授予，需重新确认。卸载或停用后，下一次调用立即被拒绝；正在读取记录的旧调用在交付结果前也会再次检查安装、版本、配置及授权是否变化。

启用设置属于当前 owner，按用户分别保存。退出服务会关闭旧执行器，但正常重启保留已安装插件和用户选择；成功恢复数据库后，所有插件停用并清除数据同意，须重新启用。目录访问授权仍是独立机制，重启即失效。

## 三个可运行工作流

| 插件 | 所需权限 | 实际行为与边界 |
| --- | --- | --- |
| 智能组卷 `exam-builder` | `question_bank` | 按年级、知识点、数量和种子轮换抽取现有课程参考题，尽量均衡覆盖知识点；同范围和 seed 可复现。可选择不附答案。 |
| 错题复盘 `mistake-review` | `read_learning_records` | 读取当前用户未被排除的错误或部分正确判定，关联实际原题与学生步骤。缺少原文会明确标记；自述不被制造成错题判定。 |
| 学情可视化 `learning-report` | `read_learning_records` | 对真实独立整题观察分窗统计准确率与技能计数，另外展示提示后、看解答后和自述数量，在页面展示折线图，并提供对应数据。 |

组卷的参考答案与解析来自本地题库，`student_steps_auto_verified` 始终为 `false`：参考答案可供核对，不表示已自动验证学生自由证明或整段讲解。高级组卷可设置 `focus_weak_skills: true`，但包必须另外声明且用户授予 `read_learning_records`。它只使用既有技能图中可定位的真实错误观察；不能推断未检查过的高中知识点已掌握或未掌握。

学情准确率为“该窗口独立整题正确观察数 ÷ 独立整题观察数”，不是掌握率、DKT 概率、测验成绩或标准化能力分数。重复、被排除、不确定和非独立整题观察不能抬高独立统计；多技能任务的整体观察与可定位到单项技能的观察分开。没有记录时返回 `status: empty`、空序列和 `null` 准确率，不补造零分或满分。

所有工作流只读题库或用户记录，不写学习事件、掌握事实、DKT、练习发布状态或用户系统文件，也不调用付费模型。插件运行结果不是学习判定证据。

## 数据流和权限

社区资源源站只提供包与说明，不接收运行结果。点击页面运行后，统计和组卷在本地服务完成，完整结果由前端下载；服务不持久保存报告或错题原文副本。

在对话中使用时，应用只提供单一的 `ext_community_run` 工具，工具范围只列出**当前 owner 已启用的插件**。只有用户实际在对话中调用，插件结果的有界投影才会提供给当前对话模型；云模型会因此收到投影里的题目或学习记录片段。不会把 owner 的记录自动上传给插件作者或社区源。完整结果应在插件页面保存，模型投影明确标注是否为部分结果。

导入的 README、更新说明和教学指导均是作者提供的参考内容，不是系统指令。即使用户此前授权了可写目录，插件说明也不能授予本轮写入权限：内置文件写入工具还需宿主从原始当前请求识别明确文件保存、创建或修改意图。普通“写一份讲解”、否定写入、工具内容和修复反馈都不会提升为文件写入授权。

## 插件包格式

可直接修改 [三份完整示例](../examples/community-plugins/) 的作者、ID、说明、教学指导与有界默认参数，导入应用测试后导出分享。命名时使用自己的 ID 前缀，升级时提高版本号，并使用有权授予的许可。

```json
{
  "schema_version": "mathtutor.community-plugin.v1",
  "kind": "teaching-plugin",
  "id": "example.grade12-weekly",
  "version": "1.0.0",
  "name": "高三每周练习",
  "description": "按知识点均衡抽取高三复习参考题。",
  "author": "示例作者",
  "license": "Apache-2.0",
  "tags": ["高三", "组卷"],
  "grades": [12],
  "readme": "先独立作答，再按需查看解析。",
  "changelog": "1.0.0：首次发布。",
  "workflow": "exam-builder",
  "defaults": {"grade": 12, "question_count": 8, "seed": 42, "point_codes": [], "include_answers": false, "focus_weak_skills": false},
  "teaching_guidance": "请学生先解释所用方法的适用条件。",
  "required_permissions": ["question_bank"]
}
```

未知顶层或配置字段会被拒绝。包最多 64 KiB，README 最多 12000 字符，教学指导最多 2000 字符，当前每个 owner 最多安装 32 个包。`exam-builder` 最多 20 题，`mistake-review` 最多 30 项，`learning-report` 最多读取最近 1000 条已接受事件作统计。种子、数量、年级和窗口大小均有严格类型与范围限制。

当前不支持社区自定义任意新执行算法、安装脚本、插件间代码依赖、MCP、网络请求或目录读写权限。需要新的执行能力时，应先由应用维护者增加受控工作流，或走可信开发者 SDK 的代码评审和发布流程。

## 管理 API 与结果

以下路由使用现有 owner 认证；修改、运行路由另外限制浏览器 Origin，拒绝外站或 `null` Origin 触发操作。

```text
GET    /api/v2/math-tutor/desktop/community/plugins
GET    /api/v2/math-tutor/desktop/community/plugins/examples
POST   /api/v2/math-tutor/desktop/community/import   # multipart 文件自动识别
POST   /api/v2/math-tutor/desktop/community/plugins
POST   /api/v2/math-tutor/desktop/community/plugins/validate
PUT    /api/v2/math-tutor/desktop/community/plugins/{id}/enabled
PATCH  /api/v2/math-tutor/desktop/community/plugins/{id}/config
DELETE /api/v2/math-tutor/desktop/community/plugins/{id}
POST   /api/v2/math-tutor/desktop/community/plugins/{id}/run
GET    /api/v2/math-tutor/desktop/community/plugins/{id}/export
```

安装和校验 body 为 `{"package": {...}}`；`/validate` 只返回规范化包与哈希，不安装、不启用、不写配置，供创作者界面下载分享包。启用为 `{"enabled": true, "consent_permissions": ["question_bank"]}`，配置与运行覆盖为 `{"config": {...}}`。结果使用 `mathtutor.community-result.v1`，带 `workflow`、`status`、实际配置、`read_only: true`、`authority: reference_only`、结构化 `data` 和边界说明，HTTP 接口保留结构化格式；普通界面的“保存结果”转换为可阅读文本。

插件包、用户配置和授权单独存储为应用私有目录中的 owner JSON，采用原子替换，不新增学习数据库表。现有备份仅含 SQLite，不携带这些独立设置；换机时应先导出插件包，导出包不包含启用状态、同意记录或学习报告。删除学习记录后再次运行报告会读取当前空记录，不复用旧报告；维护者可调用 `clear_owner` 清除某用户的插件设置。

## 离线验证

```bash
python -m pytest tests/test_community_plugins.py tests/test_community_plugins_api.py -q
```

测试使用实际本地题库、可验证的学习记录 fixtures、真实 HTTP 路由与固定模型传输桩；不调用付费模型，不代表教学回答质量提升的分数。
