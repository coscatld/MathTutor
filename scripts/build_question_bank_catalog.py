"""Build the K-12 catalog and original reference-question JSON files.

    PYTHONPATH=src python scripts/build_question_bank_catalog.py

Chapter structure follows the People's Education Press (人教版) mathematics
textbooks; high school uses 人教A版 (2019). Practice is attached only where an
existing verifiable family fits; demos only where the scene reader parses them.
Every curriculum point also has separate original reference questions; these
do not claim automatic verification of arbitrary student proofs.
"""
import json
from pathlib import Path

from mathtutor.question_bank.curriculum_content import ADDITIONAL_POINTS, ADDITIONAL_UNITS, build_reference_questions

A, P, L, LI, Q, QI, S = "arithmetic", "polynomial", "linear", "linear_inequality", "quadratic", "quadratic_inequality", "linear_system"


def pt(title, practice=(), demos=()):
    return {"title": title, "practice": [{"family": f, "template": t, "count": 6} for f, t in practice],
            "demos": [{"title": d, "request": r} for d, r in demos]}


TERMS = [
    ("g1a", "primary", 1, "一年级上册", [
        ("准备课", [pt("数一数"), pt("比多少")]),
        ("位置", [pt("上、下、前、后"), pt("左、右")]),
        ("1~5的认识和加减法", [pt("1~5的认识"), pt("5以内的加法", [(A, "add_within_10")]), pt("5以内的减法", [(A, "add_within_10")])]),
        ("认识图形（一）", [pt("长方体、正方体、圆柱和球")]),
        ("6~10的认识和加减法", [pt("6~10的认识"), pt("10以内的加减法", [(A, "add_within_10")]), pt("连加连减")]),
        ("11~20各数的认识", [pt("11~20各数的认识"), pt("10加几和相应的减法", [(A, "add_within_20")])]),
        ("认识钟表", [pt("认识整时")]),
        ("20以内的进位加法", [pt("9加几", [(A, "add_within_20")]), pt("8、7、6加几", [(A, "add_within_20")]), pt("5、4、3、2加几", [(A, "add_within_20")])]),
    ]),
    ("g1b", "primary", 1, "一年级下册", [
        ("认识图形（二）", [pt("认识平面图形"), pt("图形的拼组")]),
        ("20以内的退位减法", [pt("十几减9", [(A, "add_within_20")]), pt("十几减8、7、6", [(A, "add_within_20")]), pt("十几减5、4、3、2", [(A, "add_within_20")])]),
        ("分类与整理", [pt("按给定标准分类"), pt("自选标准分类")]),
        ("100以内数的认识", [pt("数数、数的组成"), pt("读数、写数"), pt("数的顺序、比较大小")]),
        ("认识人民币", [pt("认识人民币"), pt("简单的计算")]),
        ("100以内的加法和减法（一）", [pt("整十数加、减整十数", [(A, "add_within_100")]), pt("两位数加一位数、整十数", [(A, "add_within_100")]), pt("两位数减一位数、整十数", [(A, "add_within_100")])]),
        ("找规律", [pt("图形和数的规律")]),
    ]),
    ("g2a", "primary", 2, "二年级上册", [
        ("长度单位", [pt("认识厘米和米"), pt("认识线段")]),
        ("100以内的加法和减法（二）", [pt("两位数加两位数", [(A, "add_within_100")]), pt("两位数减两位数", [(A, "add_within_100")]), pt("连加、连减和加减混合", [(A, "add_within_100")])]),
        ("角的初步认识", [pt("认识角"), pt("认识直角、锐角、钝角")]),
        ("表内乘法（一）", [pt("乘法的初步认识"), pt("2~6的乘法口诀", [(A, "times_table")])]),
        ("观察物体（一）", [pt("从不同位置观察物体")]),
        ("表内乘法（二）", [pt("7、8、9的乘法口诀", [(A, "times_table")])]),
        ("认识时间", [pt("认识几时几分")]),
        ("数学广角——搭配（一）", [pt("简单的排列与组合")]),
    ]),
    ("g2b", "primary", 2, "二年级下册", [
        ("数据收集整理", [pt("用调查法收集数据")]),
        ("表内除法（一）", [pt("除法的初步认识"), pt("用2~6的乘法口诀求商", [(A, "times_table")])]),
        ("图形的运动（一）", [pt("轴对称图形"), pt("平移和旋转")]),
        ("表内除法（二）", [pt("用7、8、9的乘法口诀求商", [(A, "times_table")])]),
        ("混合运算", [pt("同级运算", [(A, "mixed_operations")]), pt("含有括号的混合运算", [(A, "mixed_operations")])]),
        ("有余数的除法", [pt("有余数除法的意义"), pt("解决问题")]),
        ("万以内数的认识", [pt("1000以内数的认识"), pt("10000以内数的认识"), pt("整百、整千数加减法")]),
        ("克和千克", [pt("认识克和千克")]),
        ("数学广角——推理", [pt("简单的推理")]),
    ]),
    ("g3a", "primary", 3, "三年级上册", [
        ("时、分、秒", [pt("秒的认识"), pt("时间的计算")]),
        ("万以内的加法和减法（一）", [pt("两位数加减两位数（口算）", [(A, "add_within_100")])]),
        ("测量", [pt("毫米、分米的认识"), pt("千米的认识"), pt("吨的认识")]),
        ("万以内的加法和减法（二）", [pt("三位数加三位数", [(A, "add_within_10000")]), pt("三位数减三位数", [(A, "add_within_10000")])]),
        ("倍的认识", [pt("倍的认识"), pt("求一个数是另一个数的几倍")]),
        ("多位数乘一位数", [pt("口算乘法"), pt("笔算乘法", [(A, "mul_one_digit")])]),
        ("长方形和正方形", [pt("四边形"), pt("周长", demos=[("长方形的周长", "画出四边形 ABCD，A(0,0)，B(4,0)，C(4,3)，D(0,3)")])]),
        ("分数的初步认识", [pt("几分之一"), pt("简单的分数加减法", [(A, "fraction_add_same_den")])]),
        ("数学广角——集合", [pt("集合的初步认识")]),
    ]),
    ("g3b", "primary", 3, "三年级下册", [
        ("位置与方向（一）", [pt("认识东、南、西、北"), pt("认识东北、西北、东南、西南")]),
        ("除数是一位数的除法", [pt("口算除法"), pt("笔算除法", [(A, "div_one_digit")])]),
        ("复式统计表", [pt("复式统计表")]),
        ("两位数乘两位数", [pt("口算乘法"), pt("笔算乘法", [(A, "mul_two_digit")])]),
        ("面积", [pt("面积和面积单位"), pt("长方形、正方形面积的计算")]),
        ("年、月、日", [pt("年、月、日"), pt("24时计时法")]),
        ("小数的初步认识", [pt("认识小数"), pt("简单的小数加减法", [(A, "decimal_add")])]),
        ("数学广角——搭配（二）", [pt("搭配问题")]),
    ]),
    ("g4a", "primary", 4, "四年级上册", [
        ("大数的认识", [pt("亿以内数的认识"), pt("亿以上数的认识"), pt("计算工具的认识")]),
        ("公顷和平方千米", [pt("公顷和平方千米")]),
        ("角的度量", [pt("线段、直线、射线"), pt("角的度量与分类")]),
        ("三位数乘两位数", [pt("笔算乘法", [(A, "mul_three_by_two")]), pt("积的变化规律")]),
        ("平行四边形和梯形", [pt("平行与垂直", demos=[("两条平行线", "画出 y=x+1 和 y=x-2")]), pt("平行四边形和梯形")]),
        ("除数是两位数的除法", [pt("口算除法"), pt("笔算除法", [(A, "div_two_digit")]), pt("商的变化规律")]),
        ("条形统计图", [pt("条形统计图")]),
        ("数学广角——优化", [pt("合理安排时间")]),
    ]),
    ("g4b", "primary", 4, "四年级下册", [
        ("四则运算", [pt("加、减法的意义和各部分间的关系"), pt("乘、除法的意义和各部分间的关系"), pt("括号与运算顺序", [(A, "mixed_operations")])]),
        ("观察物体（二）", [pt("从不同方向观察几何组合体")]),
        ("运算定律", [pt("加法运算定律"), pt("乘法运算定律"), pt("简便计算", [(A, "mixed_operations")])]),
        ("小数的意义和性质", [pt("小数的意义和读写"), pt("小数的性质和大小比较"), pt("小数点移动引起小数大小的变化")]),
        ("三角形", [pt("三角形的特性"), pt("三角形的分类"), pt("三角形的内角和", demos=[("三角形的三个内角", "画出三角形 ABC，A(0,0)，B(5,0)，C(m,3)，∠BAC，∠ABC，∠ACB")])]),
        ("小数的加法和减法", [pt("小数加减法", [(A, "decimal_add")]), pt("小数加减混合运算", [(A, "decimal_add")])]),
        ("图形的运动（二）", [pt("轴对称"), pt("平移")]),
        ("平均数与条形统计图", [pt("平均数"), pt("复式条形统计图")]),
        ("数学广角——鸡兔同笼", [pt("鸡兔同笼", [(S, "elimination")])]),
    ]),
    ("g5a", "primary", 5, "五年级上册", [
        ("小数乘法", [pt("小数乘整数"), pt("小数乘小数", [(A, "decimal_mul")]), pt("积的近似数")]),
        ("位置", [pt("用数对确定位置", demos=[("在方格中找点", "画出点 A(2,3) 和 B(5,1) 的线段 AB")])]),
        ("小数除法", [pt("除数是整数的小数除法"), pt("一个数除以小数", [(A, "decimal_div")]), pt("循环小数")]),
        ("可能性", [pt("可能性")]),
        ("简易方程", [pt("用字母表示数"), pt("方程的意义"), pt("解方程", [(L, "simple_equation")]), pt("实际问题与方程", [(L, "two_step")])]),
        ("多边形的面积", [pt("平行四边形的面积"), pt("三角形的面积", demos=[("底不变，顶点平移，面积不变", "画出三角形 ABC，A(0,0)，B(4,0)，C(m,3)，三角形ABC的面积")]), pt("梯形的面积")]),
        ("数学广角——植树问题", [pt("植树问题")]),
    ]),
    ("g5b", "primary", 5, "五年级下册", [
        ("观察物体（三）", [pt("根据视图还原立体图形")]),
        ("因数与倍数", [pt("因数和倍数"), pt("2、5、3的倍数的特征"), pt("质数和合数")]),
        ("长方体和正方体", [pt("长方体和正方体的认识"), pt("表面积"), pt("体积")]),
        ("分数的意义和性质", [pt("分数的意义"), pt("真分数和假分数"), pt("分数的基本性质"), pt("约分与通分")]),
        ("图形的运动（三）", [pt("旋转")]),
        ("分数的加法和减法", [pt("同分母分数加、减法", [(A, "fraction_add_same_den")]), pt("异分母分数加、减法", [(A, "fraction_add_diff_den")]), pt("分数加减混合运算", [(A, "fraction_add_diff_den")])]),
        ("折线统计图", [pt("折线统计图")]),
        ("数学广角——找次品", [pt("找次品")]),
    ]),
    ("g6a", "primary", 6, "六年级上册", [
        ("分数乘法", [pt("分数乘整数"), pt("分数乘分数", [(A, "fraction_mul")]), pt("解决问题")]),
        ("位置与方向（二）", [pt("用方向和距离确定位置")]),
        ("分数除法", [pt("倒数的认识"), pt("分数除法", [(A, "fraction_div")]), pt("解决问题")]),
        ("比", [pt("比的意义"), pt("比的基本性质"), pt("比的应用")]),
        ("圆", [pt("圆的认识", demos=[("半径为 r 的圆", "画出 x^2+y^2=r^2")]), pt("圆的周长"), pt("圆的面积")]),
        ("百分数（一）", [pt("百分数的意义和写法"), pt("百分数和分数、小数的互化")]),
        ("扇形统计图", [pt("扇形统计图")]),
        ("数学广角——数与形", [pt("数与形")]),
    ]),
    ("g6b", "primary", 6, "六年级下册", [
        ("负数", [pt("负数的认识"), pt("在数轴上表示正数、0和负数")]),
        ("百分数（二）", [pt("折扣"), pt("成数"), pt("税率"), pt("利率")]),
        ("圆柱与圆锥", [pt("圆柱的表面积和体积"), pt("圆锥的体积")]),
        ("比例", [pt("比例的意义和基本性质"), pt("正比例和反比例", demos=[("正比例关系", "画出 y=k*x"), ("反比例关系", "画出 y=k/x")]), pt("比例尺")]),
        ("数学广角——鸽巢问题", [pt("鸽巢问题")]),
        ("整理和复习", [pt("数与代数", [(A, "mixed_operations")]), pt("图形与几何"), pt("统计与概率")]),
    ]),
    # --- 初中 ---------------------------------------------------------------
    ("g7a", "middle", 7, "七年级上册", [
        ("第一章 有理数", [pt("正数和负数"), pt("数轴、相反数、绝对值"), pt("有理数的加减法", [(A, "negative_numbers")]), pt("有理数的乘除法与乘方", [(A, "rational_mixed")])]),
        ("第二章 整式的加减", [pt("整式"), pt("合并同类项", [(P, "combine_like_terms")]), pt("去括号与整式的加减", [(P, "expand_brackets")])]),
        ("第三章 一元一次方程", [pt("一元一次方程"), pt("解一元一次方程——合并同类项与移项", [(L, "two_step"), (L, "move_terms")]), pt("解一元一次方程——去括号与去分母", [(L, "brackets"), (L, "fractions")]), pt("实际问题与一元一次方程", [(L, "two_step")])]),
        ("第四章 几何图形初步", [pt("几何图形"), pt("直线、射线、线段", demos=[("线段、射线和直线", "画出点 A(0,0)，B(3,2)，线段 AB，射线 AB")]), pt("角")]),
    ]),
    ("g7b", "middle", 7, "七年级下册", [
        ("第五章 相交线与平行线", [pt("相交线"), pt("平行线及其判定", demos=[("平行线", "画出 y=2x+1 和 y=2x-3")]), pt("平行线的性质"), pt("平移")]),
        ("第六章 实数", [pt("平方根"), pt("立方根"), pt("实数")]),
        ("第七章 平面直角坐标系", [pt("平面直角坐标系", demos=[("坐标系中的点", "画出点 A(-2,1) 和 B(3,4) 的线段 AB")]), pt("坐标方法的简单应用")]),
        ("第八章 二元一次方程组", [pt("二元一次方程组"), pt("消元——代入法", [(S, "substitution")]), pt("消元——加减法", [(S, "elimination")]), pt("实际问题与二元一次方程组", [(S, "elimination")])]),
        ("第九章 不等式与不等式组", [pt("不等式及其性质", [(LI, "one_step")]), pt("一元一次不等式", [(LI, "flip_sign")]), pt("一元一次不等式组", demos=[("不等式组表示的区域", "画出 y>=x-1 与 y<=-x+3")])]),
        ("第十章 数据的收集、整理与描述", [pt("统计调查"), pt("直方图")]),
    ]),
    ("g8a", "middle", 8, "八年级上册", [
        ("第十一章 三角形", [pt("与三角形有关的线段"), pt("与三角形有关的角", demos=[("三角形内角和", "画出三角形 ABC，A(0,0)，B(5,0)，C(m,3)，∠BAC，∠ABC，∠ACB")]), pt("多边形及其内角和")]),
        ("第十二章 全等三角形", [pt("全等三角形"), pt("三角形全等的判定"), pt("角的平分线的性质")]),
        ("第十三章 轴对称", [pt("轴对称"), pt("画轴对称图形"), pt("等腰三角形"), pt("最短路径问题")]),
        ("第十四章 整式的乘法与因式分解", [pt("整式的乘法", [(P, "multiply_binomials")]), pt("乘法公式", [(P, "square_of_binomial")]), pt("因式分解")]),
        ("第十五章 分式", [pt("分式"), pt("分式的运算", [(A, "fraction_add_diff_den")]), pt("分式方程")]),
    ]),
    ("g8b", "middle", 8, "八年级下册", [
        ("第十六章 二次根式", [pt("二次根式"), pt("二次根式的乘除"), pt("二次根式的加减")]),
        ("第十七章 勾股定理", [pt("勾股定理", demos=[("直角三角形的三边", "画出三角形 ABC，A(0,0)，B(4,0)，C(0,3)，|BC|，|AB|，|AC|")]), pt("勾股定理的逆定理")]),
        ("第十八章 平行四边形", [pt("平行四边形"), pt("特殊的平行四边形")]),
        ("第十九章 一次函数", [pt("函数"), pt("一次函数", demos=[("k、b 对直线的影响", "画出 y=kx+b")]), pt("课题学习 选择方案")]),
        ("第二十章 数据的分析", [pt("数据的集中趋势"), pt("数据的波动程度")]),
    ]),
    ("g9a", "middle", 9, "九年级上册", [
        ("第二十一章 一元二次方程", [pt("一元二次方程"), pt("配方法", [(Q, "complete_square")]), pt("公式法与因式分解法", [(Q, "factorable"), (Q, "leading_coefficient")]), pt("根的判别式", [(Q, "no_real_root")]), pt("实际问题与一元二次方程", [(Q, "factorable")])]),
        ("第二十二章 二次函数", [pt("二次函数的图象和性质", demos=[("a、h、k 对抛物线的影响", "画出 y=a(x-h)^2+k")]), pt("二次函数与一元二次方程", demos=[("抛物线与 x 轴的交点", "画出 y=x^2-2x-3 的图像")]), pt("实际问题与二次函数")]),
        ("第二十三章 旋转", [pt("图形的旋转"), pt("中心对称")]),
        ("第二十四章 圆", [pt("圆的有关性质", demos=[("圆上的动点", "演示圆 x^2+y^2=4 上的动点 P(2cos t,2sin t)，A(-2,0)，B(2,0)，∠APB")]), pt("点和圆、直线和圆的位置关系", demos=[("直线与圆", "画出 x^2+y^2=4 和 y=kx+2")]), pt("正多边形和圆"), pt("弧长和扇形面积")]),
        ("第二十五章 概率初步", [pt("随机事件与概率"), pt("用列举法求概率"), pt("用频率估计概率")]),
    ]),
    ("g9b", "middle", 9, "九年级下册", [
        ("第二十六章 反比例函数", [pt("反比例函数", demos=[("k 对双曲线的影响", "画出 y=k/x")]), pt("实际问题与反比例函数")]),
        ("第二十七章 相似", [pt("图形的相似"), pt("相似三角形"), pt("位似")]),
        ("第二十八章 锐角三角函数", [pt("锐角三角函数", demos=[("直角三角形中的边角关系", "画出三角形 ABC，A(0,0)，B(4,0)，C(4,m)，∠BAC，|BC|，|AC|")]), pt("解直角三角形及其应用")]),
        ("第二十九章 投影与视图", [pt("投影"), pt("三视图")]),
    ]),
    # --- 高中（人教A版 2019）-------------------------------------------------
    ("h1a", "high", 10, "高一上 · 必修第一册", [
        ("第一章 集合与常用逻辑用语", [pt("集合的概念与表示"), pt("集合间的基本关系与运算"), pt("充分条件与必要条件"), pt("全称量词与存在量词")]),
        ("第二章 一元二次函数、方程和不等式", [pt("等式性质与不等式性质"), pt("基本不等式"), pt("二次函数与一元二次方程、不等式", [(Q, "factorable"), (QI, "two_roots_outside"), (QI, "two_roots_between"), (QI, "perfect_square")], [("抛物线与 x 轴围出的解集", "画出 y=x^2-x-2 和 y>x^2-x-2 的区域")])]),
        ("第三章 函数的概念与性质", [pt("函数的概念及其表示"), pt("函数的基本性质", demos=[("单调性与奇偶性", "画出 y=x^3-3x")]), pt("幂函数", demos=[("幂函数的图象", "画出 y=x^2 和 y=x^3 和 y=sqrt(x)")]), pt("函数的应用（一）")]),
        ("第四章 指数函数与对数函数", [pt("指数"), pt("指数函数", demos=[("底数 a 对图象的影响", "画出 y=a^x")]), pt("对数"), pt("对数函数", demos=[("指数函数与对数函数互为反函数", "画出 y=e^x 和 y=ln(x) 和 y=x")]), pt("函数的应用（二）")]),
        ("第五章 三角函数", [pt("任意角和弧度制"), pt("三角函数的概念", demos=[("单位圆上的点", "演示圆 x^2+y^2=1 上的动点 P(cos t,sin t)，O(0,0)，A(1,0)，∠AOP")]), pt("诱导公式"), pt("三角函数的图象与性质", demos=[("正弦曲线", "画出 y=sin(x) 和 y=cos(x)")]), pt("函数 y=Asin(ωx+φ)", demos=[("A、ω、φ 对图象的影响", "画出 y=a*sin(b*x+c)")]), pt("三角恒等变换")]),
    ]),
    ("h1b", "high", 10, "高一下 · 必修第二册", [
        ("第六章 平面向量及其应用", [pt("平面向量的概念与线性运算"), pt("平面向量基本定理及坐标表示", demos=[("向量的坐标", "画出点 O(0,0)，A(3,2)，B(1,4)，向量 OA，向量 OB")]), pt("平面向量的应用（正弦定理、余弦定理）", demos=[("三角形的边与角", "画出三角形 ABC，A(0,0)，B(5,0)，C(m,3)，|BC|，∠BAC")])]),
        ("第七章 复数", [pt("复数的概念"), pt("复数的四则运算"), pt("复数的三角表示")]),
        ("第八章 立体几何初步", [pt("基本立体图形"), pt("简单几何体的表面积与体积"), pt("空间点、直线、平面之间的位置关系"), pt("空间直线、平面的平行"), pt("空间直线、平面的垂直")]),
        ("第九章 统计", [pt("随机抽样"), pt("用样本估计总体")]),
        ("第十章 概率", [pt("随机事件与概率"), pt("事件的相互独立性"), pt("频率与概率")]),
    ]),
    ("h2a", "high", 11, "高二上 · 选择性必修第一册", [
        ("第一章 空间向量与立体几何", [pt("空间向量及其运算"), pt("空间向量基本定理"), pt("空间向量及其运算的坐标表示"), pt("空间向量的应用")]),
        ("第二章 直线和圆的方程", [pt("直线的倾斜角与斜率", demos=[("斜率与倾斜角", "画出 y=kx+1")]), pt("直线的方程"), pt("直线的交点坐标与距离公式", demos=[("两条直线的交点", "画出 y=2x-1 和 y=-x+5")]), pt("圆的方程", demos=[("圆心与半径", "画出 (x-a)^2+(y-b)^2=4")]), pt("直线与圆、圆与圆的位置关系", demos=[("直线与圆的位置关系", "画出 x^2+y^2=4 和 y=kx+2")])]),
        ("第三章 圆锥曲线的方程", [pt("椭圆", demos=[("椭圆上的点到焦点的距离", "演示椭圆 x^2/4+y^2/3=1 上的动点 P(2cos t, √3 sin t) 到焦点 F(1,0) 的距离")]), pt("双曲线", demos=[("双曲线与渐近线", "画出 x^2/4-y^2=1 和 y=x/2 和 y=-x/2")]), pt("抛物线", demos=[("抛物线与焦点弦", "画出 y^2=4x 和 y=k(x-1)")])]),
    ]),
    ("h2b", "high", 11, "高二下 · 选择性必修第二册", [
        ("第四章 数列", [pt("数列的概念"), pt("等差数列"), pt("等比数列"), pt("数学归纳法")]),
        ("第五章 一元函数的导数及其应用", [pt("导数的概念及其意义"), pt("导数的运算"), pt("导数在研究函数中的应用", demos=[("切线斜率与单调性", "画出 y=x^3-3x 和点 A(a, a^3-3a)")])]),
    ]),
    ("h3a", "high", 12, "高三上 · 选择性必修第三册", [
        ("第六章 计数原理", [pt("分类加法计数原理与分步乘法计数原理"), pt("排列与组合"), pt("二项式定理")]),
        ("第七章 随机变量及其分布", [pt("条件概率与全概率公式"), pt("离散型随机变量及其分布列"), pt("二项分布与超几何分布"), pt("正态分布", demos=[("正态曲线", "画出 y=exp(-x^2/2)/sqrt(2*pi)")])]),
        ("第八章 成对数据的统计分析", [pt("成对数据的统计相关性"), pt("一元线性回归模型及其应用"), pt("列联表与独立性检验")]),
    ]),
    ("h3b", "high", 12, "高三下 · 总复习（专题）", [
        ("专题一 函数与导数", [pt("函数的图象与性质", demos=[("函数图象变换", "画出 y=a*(x-h)^2+k")]), pt("导数与函数的单调性、极值")]),
        ("专题二 三角函数与解三角形", [pt("三角函数的图象与性质", demos=[("y=Asin(ωx+φ)", "画出 y=a*sin(b*x+c)")]), pt("解三角形")]),
        ("专题三 数列", [pt("等差数列与等比数列"), pt("数列求和")]),
        ("专题四 不等式", [pt("一元二次不等式", [(QI, "two_roots_outside"), (QI, "two_roots_between")]), pt("基本不等式")]),
        ("专题五 立体几何", [pt("空间位置关系"), pt("空间角与距离")]),
        ("专题六 解析几何", [pt("直线与圆"), pt("圆锥曲线", demos=[("椭圆上的动点", "演示椭圆 x^2/4+y^2/3=1 上的动点 P(2cos t, √3 sin t) 到焦点 F(1,0) 的距离")])]),
        ("专题七 概率与统计", [pt("概率与随机变量"), pt("统计与统计案例")]),
    ]),
]

BOOKS = {"primary": "人教版义务教育教科书 数学", "middle": "人教版义务教育教科书 数学", "high": "人教A版 普通高中教科书 数学（2019）"}


PRACTICE_OVERRIDES = {
    "g1a-u3-p2": "add_five", "g1a-u3-p3": "subtract_five",
    "g2a-u2-p1": "add_two_digit", "g2a-u2-p2": "subtract_two_digit",
    "g2a-u4-p2": "multiply_low_table", "g2a-u6-p1": "multiply_high_table",
    "g2b-u2-p2": "divide_low_table", "g2b-u4-p1": "divide_high_table",
    "g3a-u4-p1": "add_three_digit", "g3a-u4-p2": "subtract_three_digit",
    "g2a-u2-p3": "add_sub_chain", "g2b-u5-p1": "same_level_operations",
    "g2b-u5-p2": "bracket_operations", "g4b-u1-p3": "bracket_operations",
    "g4b-u3-p3": "distributive_calculation", "g4b-u6-p2": "decimal_mixed",
    "g5b-u6-p3": "fraction_mixed",
}
# These old mappings generated unrelated naked calculations instead of the
# promised word problem, restricted operation or rational algebra expression.
REFERENCE_ONLY = {
    "g1a-u6-p2", "g1a-u8-p1", "g1a-u8-p2", "g1a-u8-p3",
    "g1b-u2-p1", "g1b-u2-p2", "g1b-u2-p3",
    "g1b-u6-p1", "g1b-u6-p2", "g1b-u6-p3", "g4b-u9-p1",
    "g5a-u5-p4", "g7a-u3-p4", "g7b-u4-p4", "g8a-u5-p2", "g9a-u1-p5",
}


def build():
    terms = []
    for order, (code, stage, grade, label, units) in enumerate(TERMS, 1):
        terms.append({"code": code, "stage": stage, "grade": grade, "order": order, "label": label,
                      "book": f"{BOOKS[stage]} {label.split(' · ')[-1]}",
                      "units": [{"code": f"{code}-u{u}", "title": title,
                                 "points": [{"code": f"{code}-u{u}-p{i}", **point} for i, point in enumerate(points, 1)]}
                                for u, (title, points) in enumerate(units, 1)]})
    references = build_reference_questions()
    for term in terms:
        term["recommended_grades"] = [11, 12] if term["code"] == "h3a" else [term["grade"]]
        for title, titles in ADDITIONAL_UNITS.get(term["code"], ()):
            unit_code = f"{term['code']}-u{len(term['units']) + 1}"
            term["units"].append({"code": unit_code, "title": title,
                                  "points": [{"code": f"{unit_code}-p{i}", **pt(label)} for i, label in enumerate(titles, 1)]})
        for unit in term["units"]:
            for title in ADDITIONAL_POINTS.get(unit["code"], ()):
                unit["points"].append({"code": f"{unit['code']}-p{len(unit['points']) + 1}", **pt(title)})
            for point in unit["points"]:
                if point["code"] in PRACTICE_OVERRIDES:
                    point["practice"] = [{"family": A, "template": PRACTICE_OVERRIDES[point["code"]], "count": 6}]
                if point["code"] in REFERENCE_ONLY:
                    point["practice"] = []
                point["reference_ids"] = [q["id"] for q in references[point["code"]]]
    codes = {p["code"] for t in terms for u in t["units"] for p in u["points"]}
    if codes != set(references):
        raise ValueError(f"Missing/extra reference mappings: {codes ^ set(references)}")
    return {"version": "k12-pep-v2", "source_note": "参照人教版（高中为人教A版 2019）教材目录整理；各校进度可能不同；选择性必修第三册适用于高二至高三，高三下按专题复习组织。课程题附参考答案，作答过程未自动核验。",
            "terms": terms}


if __name__ == "__main__":
    out = Path("src/mathtutor/question_bank/catalog_k12_v1.json")
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    references = build_reference_questions()
    question_out = out.with_name("curriculum_questions_v2.json")
    question_out.write_text(json.dumps({"version": "k12-original-v2", "license": "Apache-2.0",
                                      "authorship": "MathTutor original deterministic curriculum exercises",
                                      "questions": references}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    catalog = json.loads(out.read_text(encoding="utf-8"))
    points = [p for t in catalog["terms"] for u in t["units"] for p in u["points"]]
    print(f"terms {len(catalog['terms'])}, units {sum(len(t['units']) for t in catalog['terms'])}, points {len(points)}, "
          f"with practice {sum(bool(p['practice']) for p in points)}, with demos {sum(bool(p['demos']) for p in points)}")
