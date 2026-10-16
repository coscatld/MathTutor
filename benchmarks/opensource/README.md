# 开源数学文本评测工具与方法

本目录提供 MathTutor 产品入口的评测工具、资料界限、分割和评分流程。它是对四套公开基准的固定抽样适配，不是原作者的官方评测包。原始题库、参考答案、rubric 和模型输出不放进产品仓库；本地完整材料由实验目录保存。

- 方法：`PROTOCOL.md`、`METHOD_NOTES.md`、`SCHEMA.md`。
- 范围：`inventory.json`、`source_manifest.json`。
- 数据许可：`ATTRIBUTION.md`；评测代码沿用 Apache-2.0。
- 测试结果：仓库 `docs/eval/OPEN_SOURCE_BENCHMARK_20261016.md`。

执行环境为 macOS、Python 3.13、DeepSeek Flash 和已认证的 Claude CLI 2.1.300（实际评审模型 Opus 4.7）。生成器以每题独立进程运行真实 WebSocket 入口；当前超时机制使用 POSIX SIGALRM。产品本身仍由三平台 CI 检查。

保持实验目录布局：`WORK/MathTutor` 是产品仓库，`WORK/开源benemark` 中放置四个原始数据仓库以及 `evaluation` 数据目录。安装依赖后，将工具指向实验目录：

```bash
export MATHTUTOR_BENCHMARK_ROOT="/absolute/path/to/开源benemark/evaluation"
python scripts/check_integrity.py
python scripts/run_product.py --split dev --config /tmp/local-benchmark.json \
  --output "$MATHTUTOR_BENCHMARK_ROOT/results/NEW_RUN/dev" --workers 12
python scripts/score_objective.py --run NEW_RUN --split dev
```

初次准备依次运行 `fetch_data.py` 和 `prepare.py`，核对冻结输入摘要。源 Git 提交固定在 `source_manifest.json`；重新下载的数据若摘要不同，就不是同一实验输入。`MATHTUTOR_BENCHMARK_CONFIG` 可配置本地模型代理连接文件，`CLAUDE_BIN` 可配置 CLI 可执行文件；凭据不写入源码或结果。

发布副本增加实验根目录和 CLI 路径配置，并清理一处行尾空白。本地定稿脚本摘要及发布副本摘要分别记在 `published_script_manifest.json`；实际调用时记录的摘要另见各轮 manifest；本地归档保留定稿工具、历史版本（若有）和全部原始结果。不得把路径适配后的脚本冒充与原执行脚本逐字节相同。

评审后运行 `normalize_judge.py REVIEW_LABEL` 验证编号与 rubric 完整性，再运行 `parse_judge.py REVIEW_LABEL`；只对结构无效评审重试，不重新生成智能体回答，不按分数择优。候选仅根据开发集选择，测试结果用于最终报告。

`snapshot.py` 仅复制当前存在的候选修改文件。开发选择的严格门槛无候选通过；本轮按已公开的三轮上限例外冻结第 2 轮，未通过的门槛仍标为 false。不能直接重新运行选择器覆盖本轮已冻结的 selection.json。
