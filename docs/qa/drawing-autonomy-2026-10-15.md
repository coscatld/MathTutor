# 0.6.1 本机作图修复验证

基线：`v0.6.1` / `3685c25acc7001f5040f7e2ad76b1033b161fcdf`。
分支：`fix/hyperbola-drawing-061`。修改位于独立 worktree `MathTutor-drawing-fix`。

## 修复范围

- 「画一个图展示一下双曲线」等未指定参数的常见曲线请求，选取明确标注的标准示例，离线也可生成可拖动参数的画布。
- 「都可以」「你定」等简短回复续接最近的作图请求，支持持久化旧对话重启后恢复；不跨越新话题，也不重复已交付的图。
- 数学图形概念及简短追问向模型提供 `draw_scene`，允许主动配图、自选示例；保留已给出的条件。普通聊天沿用原路径。
- 数学验证、模型绘图定义校验、作图数量限制、学习证据和原题答案披露规则继续生效。

## 验证

```text
pytest tests/test_drawing_autonomy.py tests/test_function_graph.py
       tests/test_scene_requests.py tests/test_scene_expr.py tests/test_scene_build.py
       tests/test_canvas_drawing_skill.py tests/test_math_tool_loop.py
       tests/test_streaming_preview.py tests/test_tutor_p0.py -q --disable-warnings
237 passed
```

新回归覆盖指定方程保留、含条件请求不被标准示例替换、旧对话续接、模型主动调用画布、短追问继续提供工具、新话题不继承工具、活动练习状态不变且不披露答案点。

浏览器使用已安装 0.6.1 的前端资源和隔离数据目录的修复后端，没有读取或改写学生学习数据，也未模拟浏览器 API。输入截图原话后，画布显示「双曲线示例」，两条参数滑块可用；a 从 2 改为 3 后确认 canvas 像素发生变化，页面 JavaScript 错误为零。

浏览器记录和截图保存在同级 `MathTutor-drawing-verification-20261015`。模型工具调用测试使用模拟供应商响应；本次没有评价真实模型的讲解质量。

## 本机应用

核对已安装六个文件与发布基线（忽略换行符）一致，逐文件备份后再替换；记录替换前后 SHA-256。仅修改本机安装目录中的 Python 源文件和内置作图提示，不生成新安装包或改变版本号。完整退出并重新启动 MathTutor 后生效。

备份位置见 `MathTutor-drawing-verification-20261015/local-hotfix.json`；重新安装原版 0.6.1 会覆盖本机修复。
