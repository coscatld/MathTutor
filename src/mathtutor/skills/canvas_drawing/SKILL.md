# 画布作图技能（draw_scene）

## 什么时候配图

图能帮学生理解时才画，例如：函数图像与性质、曲线（圆、椭圆、抛物线、双曲线、极坐标曲线）、不等式表示的区域、几何关系（点、线段、多边形、圆、切线、角、距离、面积）、动点与轨迹、参数变化、数形结合的思路。学生明确要求「画图」「配个图」时也画。纯计算、概念问答、闲聊不需要图。

## 唯一的作图方式

- 要展示图形，只能调用 `draw_scene` 工具，由应用的画布绘制。这是唯一会显示给学生的图。
- 禁止用其他任何方式画图：字符画或 ASCII 图、Markdown 图片 `![...](...)`、HTML（img、svg、canvas）、SVG、Mermaid、TikZ、LaTeX 的 picture 等作图环境、作图代码（matplotlib、plotly、JavaScript 等）。这些内容会被应用删除，学生看不到。
- 不要自己写 `mathtutor-scene` 或 `mathtutor-graph` 代码块；只有应用生成的图块才会显示。
- 每次回答最多一张图，学生明确要多张图时除外（应用每轮最多接受 2 张）。
- 工具返回 `{"status":"drawn"}` 表示图已画好，会附在你的回答后面；在正文里自然地引导学生看图即可，不要描述调用过程。
- 工具返回 `{"status":"rejected","reason":…}` 时，按 reason 改正定义后再调用一次；仍然不行就放弃作图，用文字讲解。
- 无法用下面的格式表示的图（例如三维图形、立体几何、统计图表、实物插图），不要硬画，用文字说明「这类图暂时画不了」，再用文字讲清楚。

<!-- format -->
定义格式：
{"title": "≤60字标题",
 "params": [{"name": "t", "min": 0, "max": 6.2832, "step": 0.01, "value": 0.8, "animate": true}],
 "objects": [对象…],
 "readouts": [{"label": "|PF|", "expr": "dist(P,F)", "digits": 3}]}

对象（id 为 1~8 个字母或数字，互不相同）：
- {"id":"f","type":"function","expr":"x^2-2x"}            y = expr，只含 x 和参数
- {"id":"E","type":"implicit","equation":"x^2/4+y^2/3=1"}  隐式曲线，含 x、y
- {"id":"R","type":"region","inequality":"y>x^2-1"}        不等式区域（< <= > >=）
- {"id":"C","type":"parametric","x":"cos(s)","y":"sin(s)","s_range":[0,6.2832]}  参数曲线，自变量用 s
- {"id":"Q","type":"parametric","r":"2(1+cos(s))"}         极坐标 r(s)
- {"id":"P","type":"point","x":"2cos(t)","y":"sqrt(3)sin(t)","trace":true}  点，只能用参数和之前定义的点
- {"id":"PF","type":"segment","from":"P","to":"F"}         也可用 line、ray、vector
- {"id":"T","type":"polygon","points":["A","B","C"],"fill":true}
- {"id":"O","type":"circle","center":"A","radius":"2"}
- {"id":"L","type":"tangent","of":"f","at":"a"}            函数 f 在 x=a 处的切线
- {"id":"W","type":"text","x":"1","y":"2","text":"说明"}
所有对象可加 "label"（≤60字）。

表达式是字符串，只能用：数字、x、y、s、参数（单个字母，不能是 x y s e，必须在 params 里声明）、pi、e、+ - * / ^、括号、|…|，
函数 sin cos tan asin acos atan sqrt abs ln log exp floor ceil sign min max atan2，
点坐标 P.x、P.y，几何量 dist(P,A)、slope(P,A)、angle(A,B,C)（度）、area(A,B,C,…)、mid_x(A,B)、mid_y(A,B)。
<!-- /format -->

<!-- rules -->
作图规则：
- 限制：参数最多 4 个，对象最多 40 个，读数最多 8 个，标题和标签不超过 60 字。
- 只给定义，不给结果：不要计算交点、最值点、切点或答案坐标再把它们写成固定点；题目给出的点（如已知点、焦点坐标）可以直接写。需要的数值用 readouts 让应用实时计算。
- 不要输出 marks；所有坐标、交点和读数都由应用计算。
- 动点用参数驱动（例如 t，animate 设为 true），读数用 readouts 让应用实时计算。
- 图只是示意，不能作为证明：不要说「由图可知结论成立」「图证明了…」，结论仍要用推理或计算说明。
<!-- /rules -->
