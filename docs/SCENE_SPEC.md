# 数形结合场景（Scene v2）协议

函数图像（`mathtutor-graph` v1）只能画 `y = f(x)`。Scene v2 把它推广成通用的「数形结合场景」：函数、隐式曲线、参数曲线、不等式区域、点、线、多边形、圆、切线、文字，并且可以有参数滑块和动画、动点轨迹、实时读数。

## 安全边界

- 表达式只有两种来源：学生输入，或模型提出的**定义**（字符串）。服务端用白名单解析器把字符串编译成 AST；任何不在白名单内的记号直接拒绝。没有 `eval`。
- 坐标、交点、读数都由应用计算：服务端算静态标注，前端只做 AST 求值和绘制。模型不提供任何计算结果。
- 只有服务端写出的 `SHOW_GRAPH` 消息里的 `mathtutor-scene` 代码块会被渲染；其他消息中的同名代码块按普通文本显示。
- 模型提出的场景标注 `source: "model"`，界面显示「示意图：定义来自模型，图形由应用计算，未经数学核验」。
- 题目未完成时，与当前题目相关的场景不标出答案点（沿用 v1 规则）。

## 传输格式

服务端在 `SHOW_GRAPH` 消息中放一个代码块：

````
```mathtutor-scene
{ ...Scene JSON... }
```
````

v1 的 `mathtutor-graph` 代码块继续有效。

## 表达式 AST（服务端产出，前端求值）

| 节点 | 形状 | 说明 |
|---|---|---|
| 数 | `{"k":"num","v":1.5}` | 有限实数 |
| 变量 | `{"k":"var","n":"x"}` | `x`、`y`（作图变量）、`s`（参数曲线自变量）或参数名 |
| 二元运算 | `{"k":"op","o":"+","a":[A,B]}` | `o` ∈ `+ - * / ^` |
| 取负 | `{"k":"neg","a":[A]}` | |
| 函数 | `{"k":"fn","f":"sin","a":[A]}` | `sin cos tan asin acos atan sqrt abs ln log exp floor ceil sign`（一元），`min max atan2`（二元） |
| 点坐标 | `{"k":"coord","p":"P","c":"x"}` | 写作 `P.x` / `P.y`，`P` 必须是之前定义的点 |
| 几何量 | `{"k":"geo","f":"dist","p":["P","A"]}` | `dist(P,A)` 距离、`slope(P,A)` 斜率、`angle(A,B,C)` 以 B 为顶点的角（度）、`area(A,B,C,…)` 多边形面积、`mid_x(A,B)`/`mid_y(A,B)` 中点坐标 |

求值规则：任何非有限结果（除零、负数开偶次方、定义域外）记为「无定义」，绘制时断开，不报错。

## Scene JSON

```json
{
  "v": 2,
  "title": "椭圆上的动点到焦点的距离",
  "source": "deterministic",
  "x_range": [-3, 3],
  "y_range": [-2.5, 2.5],
  "equal_aspect": true,
  "params": [
    {"name": "t", "min": 0, "max": 6.2832, "step": 0.01, "value": 0.8, "animate": true, "label": "t"}
  ],
  "objects": [
    {"id": "E", "type": "implicit", "expr": AST, "label": "x²/4 + y²/3 = 1"},
    {"id": "F", "type": "point", "x": AST, "y": AST, "label": "F"},
    {"id": "P", "type": "point", "x": AST, "y": AST, "label": "P", "trace": true},
    {"id": "PF", "type": "segment", "from": "P", "to": "F"}
  ],
  "readouts": [{"label": "|PF|", "expr": AST, "digits": 3}],
  "marks": [{"x": 1, "y": 0, "label": "焦点 (1, 0)"}],
  "note": ""
}
```

### 对象类型

| type | 字段 | 含义 |
|---|---|---|
| `function` | `expr`（含 `x`），可选 `domain:[a,b]` | `y = expr` |
| `implicit` | `expr`（含 `x`、`y`） | 曲线 `expr = 0`（等式左边减右边） |
| `parametric` | `x`、`y`（含 `s`），`s_range:[a,b]` | 参数曲线；极坐标 `r(θ)` 由服务端转成 `x=r cos s, y=r sin s` |
| `region` | `expr`（含 `x`、`y`），`relation` ∈ `lt le gt ge` | 阴影：`expr relation 0` |
| `point` | `x`、`y`（不含 `x`/`y` 作图变量），可选 `trace:true` | 点，可随参数移动；`trace` 留下轨迹 |
| `segment` `line` `ray` `vector` | `from`、`to`（点 id） | 线段 / 直线 / 射线 / 向量 |
| `polygon` | `points:[id…]`，`fill:bool` | 多边形 |
| `circle` | `center`（点 id），`radius`（AST） | 圆 |
| `tangent` | `of`（function 对象 id），`at`（AST，x 坐标） | 切线，前端数值求导 |
| `text` | `x`、`y`（AST），`text` | 文字标注 |

公共可选字段：`label`（≤60 字）、`hidden`（默认 false）。

### 限制（服务端校验，前端再校验一次）

- 参数 ≤ 4 个，名字是单个字母且不能是 `x y s e`；`min < max`，`step > 0`，`value` 在范围内。
- 对象 ≤ 40 个，`id` 唯一且由字母数字组成（≤8 字符）；点只能引用**之前**定义的点；线、多边形、圆、切线引用的 id 必须存在且类型正确。
- 读数 ≤ 8 个；`marks` ≤ 12 个；每个 AST 深度 ≤ 40、节点 ≤ 400。
- `x_range`、`y_range` 有限且下界小于上界。

## 前端行为

- 函数与参数曲线：采样折线，遇到无定义或跳变断开。
- 隐式曲线：在可见区域的网格上用 marching squares 求零等值线。
- 区域：网格着色，半透明。
- 参数：每个参数一个滑块；`animate:true` 的参数有播放 / 暂停按钮，在范围内循环。
- 动点 `trace:true`：记录参数变化时的位置，画成淡色轨迹，可清除。
- 读数：随参数实时更新，无定义时显示「无定义」。
- 图下方有文字列表（对象、标注点、读数的当前值），供读屏和表格查看。
- 悬停显示坐标；支持深色风格。
