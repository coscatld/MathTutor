# E1：主动诊断探针实验

本文保留隔离实验当时的记录；其中 `repo/`、`outputs/`、`audit/` 为本地实验目录。当前源码复现入口与最终验证范围见[概念复查说明](../../11月11号更新文档/002-概念复查与学习闭环.md)。

日期：2026-11-11；seed=0；非训练 CPU 实验。仅编辑隔离副本。

## 改动

- `repo/src/mathtutor/learning/diagnostic_probes.py`：有限题库、精确数值解析、竞争规则、最大分割选题、双语题面与反馈。
- `repo/tests/test_diagnostic_probes.py`：34 项测试覆盖 93 题独立算术对照、无答案公开投影、输入预算、未知与碰撞、反证、帮助、重复和题量上界。
- `train.py`、`eval.py`：编译/冻结与固定 seed 评估 wrappers；自动定位仓库，无绝对 lab 路径。
- `data/fixtures.json`、`checkpoints/manifest.json`、`outputs/`：冻结病例、哈希、日志、分项指标和逐回合记录。

分数加法 41 题（25 诊断、8 复习、8 缺加数迁移），有符号减法 52 题（36 诊断、8 复习、8 缺被减数迁移）。每题经产品 Parser→Solver→Verifier 并与独立 Fraction 答案比对。迁移改变未知量位置，属于登记的结构变式，不称远迁移。

诊断至少两个不同独立题，最多三题；未知输入不计错也不返回答案；矛盾保留不确定，重复/跨域证据拒绝。输出仅是可撤销作答模式。服务层负责 owner、事务、取消、时间、暴露与持久化，尚未执行的服务测试不能算通过。

## 受控结果

开发域分数加法；策略未调参，整域留出有符号减法。每域 200 已知规则病例和 200 压力病例，共 800 病例 × 3 策略。所有策略共享题库、最多三题和准入条件。固定是题库顺序代理，随机按病例种子选择；二者不是产品旧版基线。200 病例重复四条作者定义规则、变化已曝光候选，不是 200 个学生。

| 留出域 | 主动 | 随机 | 固定 |
|---|---:|---:|---:|
| 正确支持模式 / 200 | 200 | 165 | 43 |
| 已支持但错误 / 200 | 0 | 0 | 0 |
| 支持覆盖率 | 100% | 82.5% | 21.5% |
| 正确支持所需题数均值 | 2.000 | 2.224 | 2.884 |

预注册覆盖分支通过：相对随机 +17.5 个百分点，超过 10 个百分点门槛。效率分支未通过：相对随机约少 10.1%，不足 15%。分数开发域主动/固定各 200/200、随机 199/200，不说明所有数学领域都会改善。

## 失败结论与集成边界

留出域单次失误和明显库外规则各 50 例，主动均未支持模式。但策略切换 50 例仍有 30 例与一个规则相容；刻意模仿相同输出的未知机制 50/50 相容。有限题目不能确定心理原因。自动稳定误概念确诊不通过；按预登记条件只接入透明、可撤销模式与追问流程。模拟结果不证明学生保持、迁移或成绩提高。

诊断 collecting 阶段不展示正确答案/纠错方法，以免两题之间教学造成策略变化；主动求助应结束独立诊断。复习与迁移分别需要新的独立证据。

## 运行与修正

核心测试 34 passed（首次 0.32s，文案修正后 0.18s）；烟测 40 回合 × 3 策略约 0.012s。预期烟测 <1 分钟、完整评估 <5 分钟，实际因有限算术规模而远短于预算。GPU/epoch 不适用，不存在 CPU fallback 或训练瓶颈。

第一轮原始源码、manifest、日志与结果保留在 `outputs/first-heldout/`。之后仅将中文错误规则文案改为“忽略减数符号”并使 wrappers 可搬入最终 repo；策略、公式、fixture 均未变化。固定原 fixture 重跑，所有计数和门槛完全一致。报告写入时一度使用了 repo 子目录导致文件不存在；随后更正工作目录，不影响实验。

## API 与复现

`catalog/get_probe/public_probe`；`parse_response -> Fraction|None`、`format_answer`；`assess_response -> correctness/normalized_answer/matching_rules/feedback`（未知时反馈 None）；`feedback_for -> answer/explanation_zh/en`；`diagnostic_state`、`choose_probe`；`choose_followup(domain, review|transfer, excluded_ids)`。observations 使用 `probe_id/answer/independent`。公开题目主键是 `probe_id`，不包含内部答案/预测。assess_response 只供服务端调用，不能完整转发客户端。

在项目依赖已安装的 Python 环境，从 wrappers 所在目录运行：

```sh
python train.py --data-dir data --checkpoint-dir checkpoints --output-dir outputs/train --seed 0
python eval.py --data-dir data --checkpoint-dir checkpoints --output-dir outputs/smoke --seed 0 --smoke
python eval.py --data-dir data --checkpoint-dir checkpoints --output-dir outputs/heldout --seed 0
```

train.py 仅编译开发题库并冻结数据，training=false；eval.py 校验 source/fixture 哈希后执行。Wrappers 可直接放到最终仓库 scripts/learning_loop/，自动发现 src/mathtutor。

## 独立审查后的测量修正

原指标把主动、固定与随机的选题耗时合并，不能当作主动策略 p95。现分别按策略记录，且不统计已终止或无题时的空操作；原记录保留在 `outputs/before-latency-fix/`。同 fixture 重跑的所有作答计数与门槛完全一致。主要效果比较使用随机策略；固定顺序容易连续选到碰撞题，只作为低信息顺序对照。200 个合成回合不是独立学生，不计算或宣称真人风险置信区间。

主动策略热 p95 为 0.101250ms；完整评估 0.159948s。

## 最终机器记录

{
  "data_load_seconds": 0.0007276250016730046,
  "catalog_compile_seconds": 0.01027675000113959,
  "total_seconds": 0.15994808400137117,
  "selection_latency_ms_by_policy": {
    "active": {
      "p50": 0.06931250027264468,
      "p95": 0.10124999971594661,
      "max": 0.4449580010259524,
      "samples": 1400
    },
    "fixed": {
      "p50": 0.00020900006347801536,
      "p95": 0.0002920005499618128,
      "max": 0.0013329990906640887,
      "samples": 1664
    },
    "random": {
      "p50": 0.0002080014382954687,
      "p95": 0.00029199873097240925,
      "max": 0.0012910004443256184,
      "samples": 1512
    }
  }
}

Fixture SHA256: db27104e605abbd3d0b4bc69c36147748324ac5b94dcc5daf0c8fb2d0ece42ac

Core SHA256: 59e82910698c55a4d39294e89fcf733f5991f35816cd4a130542beab676228a2
