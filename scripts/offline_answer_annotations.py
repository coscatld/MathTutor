"""Fresh annotations for 0.4.1 answers; never imported from original-B scores.

Each item: claim, support label, mathematical label, short reason. All are
independent AI review proposals awaiting a human, not mathematical attestations.
"""

def C(text, support="DERIVED", math="AI_NO_ERROR_FOUND", reason="可见规则的局部应用；须人工复核"):
    return dict(statement=text, evidence_support=support, mathematical_correctness=math,
                basis=reason, disputed=math in {"AI_FALSE", "AI_DISPUTED"} or support == "UNSUPPORTED")


EXPRESSION = {
"easy:canonical_term": [C("只含一个未知数", "DIRECT"), C("未知数最高次数为1", "DIRECT"),
    C("整式方程，未知数不能在分母", "DERIVED"), C("3x+5=11 是一元一次方程"),
    C("2x²-1=0 不是一次方程"), C("1/x=4 不是整式方程")],
"easy:spoken_variant": [C("两边同加或同减同一个数仍相等", "DIRECT"), C("x+3=7 同减3得x=4")],
"easy:transposition": [C("移项必须变号", "DIRECT"), C("依据两边同加减的等式性质", "DIRECT"),
    C("x+3=7 两边减3得x+3-3=7-3"), C("x=4"), C("x=7-3，移项加变减、减变加")],
"easy:formula": [C("求根公式适用于ax²+bx+c=0且a≠0", "DIRECT"), C("a二次项系数、b一次项系数、c常数项"),
    C("x=(-b±√(b²-4ac))/(2a)", "DIRECT"), C("±对应两个根；零判别式时重合", "DERIVED", reason="必须连同后文实根条件读，非无条件两个不同实根"),
    C("Δ=b²-4ac", "DIRECT"), C("Δ>0两个不等实根", "DIRECT"), C("Δ=0两个相等实根", "DIRECT"), C("Δ<0没有实根", "DIRECT")],
"easy:discriminant": [C("一般形式ax²+bx+c=0，a≠0", "UNSUPPORTED", reason="该题可见二次方程片段#2未陈述a≠0；数学条件正确，但不能当成来源原句"),
    C("Δ=b²-4ac", "DIRECT"), C("求根公式中√Δ决定实根个数", "DERIVED"),
    C("Δ>0有两个不等实根", "DIRECT"), C("Δ=0根重合，有两个相等实根，也可说只有一个实根", "DIRECT", "AI_DISPUTED", "按重数和按不同值计数两种口径，应明确‘一个不同实根’，不判算式错误"),
    C("Δ<0没有实根", "DIRECT"), C("负数在实数范围内没有平方根", "UNSUPPORTED", reason="数学正确，但摘录未陈述实平方根定义"),
    C("x²-3x+2=0 的Δ=1>0，有两个不等实根")],
"easy:commutative": [C("交换两加数位置和不变", "DIRECT"), C("a+b=b+a", "DIRECT"),
    C("3+5=8和5+3=8"), C("结合律(a+b)+c=a+(b+c)", "DIRECT"), C("结合律变分组先后，交换律变加数位置", "DIRECT")],
"easy:associative": [C("先加前两个或后两个结果不变", "DIRECT"), C("(a+b)+c=a+(b+c)", "DIRECT"),
    C("(2+3)+4=9"), C("2+(3+4)=9"), C("结合律变运算顺序，交换律变位置", "DIRECT")],
"easy:cross_topic": [C("去分母可能产生增根", "DIRECT"), C("原分母不能为0", "DIRECT"),
    C("在两边同乘最简公分母", "UNSUPPORTED", reason="操作常识正确，但本题可见片段没有明说最简公分母"),
    C("等式两边同乘0是没有意义的操作", "UNSUPPORTED", "AI_FALSE", "同乘0有定义并保留正向蕴含，但可能扩大解集而不等价；x=1与0x=0在x=0处真假不同"),
    C("1/(x-1)=2/(x-1)在定义域x≠1内无解", "DERIVED", reason="1=2矛盾；受限方程验证器不支持分式方程，整段判定为AI推理而非VERIFIED"),
    C("x/(x-1)=1/(x-1)去分母得x=1，但x=1使原式未定义", "DERIVED", reason="有定义域反例；原分式方程自动验证仍UNKNOWN"),
    C("解应代回原方程；原分母为0应舍去", "DIRECT"),
    C("整式方程去分母乘的是非零数字，一般不需这种检验", "UNSUPPORTED", "AI_DISPUTED", "仅适用于清除数值分母的语境；不能外推为整式解答不需检验，原文没有此比较")],
"easy:mixed_cjk_latex": [C("二次方程ax²+bx+c=0要求a≠0", "DIRECT"), C("a=0后二次项消失成为bx+c=0"),
    C("b≠0时才为一次方程", "DERIVED"), C("a≠0保证二次项存在", "DERIVED"),
    C("求根公式分母2a，因此a=0时公式无意义", "DERIVED")],
"hard:Q01": [C("Δ=b²-4ac", "DIRECT"), C("适用于一元二次方程ax²+bx+c=0且a≠0", "DIRECT"),
    C("不能用二次方程实根判别规则直接处理a=0", "DERIVED"),
    C("a=0就退化为一次方程", "DIRECT", "AI_FALSE", "来源原句也含错。a=b=0,c=1为矛盾；a=b=c=0为恒等式。忠于资料不能证明数学正确")],
"hard:Q02": [C("2x+3=7 两边减3得到2x=4", "DIRECT"), C("依据同减等式性质", "DIRECT"),
    C("两边除2得x=2", "DIRECT"), C("同除非零数保持等式", "DIRECT"),
    C("代回2*2+3=7"), C("移项变号依据等式性质", "DIRECT")],
"hard:Q03": [C("完全平方中间项为两数乘积的两倍", "DIRECT"), C("(a+b)²=a²+2ab+b²"),
    C("(a-b)²=a²-2ab+b²"), C("首末为a²、b²", "DIRECT"), C("中间项+2ab或-2ab取决于和差")],
"hard:Q04": [C("中间项为两数乘积的两倍", "DIRECT"), C("(a+b)²=a²+2ab+b²"), C("(a-b)²=a²-2ab+b²"),
    C("和式+2ab，差式-2ab"), C("首尾平方，中间首尾乘积两倍", "DIRECT")],
"hard:Q05": [C("二次由最高次数决定，a≠0保证x²项存在", "DIRECT"), C("a=0变成bx+c=0"),
    C("这已经是一次方程", "DIRECT", "AI_FALSE", "来源含相同漏条件错误，需b≠0；a=b=0另分c=0和c≠0"),
    C("Δ=b²-4ac", "DIRECT"), C("韦达根和=-b/a，根积=c/a", "DIRECT", "AI_DISPUTED", "a≠0且根存在于选定数域；未明确实数/复数范围，应人工审阅适用范围"),
    C("这些公式里会出现除以a的问题（将判别式并列）", "UNSUPPORTED", "AI_FALSE", "Δ=b²-4ac本身不除a；韦达和求根式才含该分母"),
    C("a=0后方法要换成解一元一次方程", "DIRECT", "AI_FALSE", "再次遗漏b=0的常量方程分支")],
}

DEGENERATE = {
"degenerate:a0": [C("a=0消去二次项，得bx+c=0"), C("b≠0为一次方程，x=-c/b"),
    C("b=0,c≠0时矛盾无解", "UNSUPPORTED", reason="逻辑正确；可见资料未列该分类，常量方程验证器UNKNOWN"),
    C("b=c=0为0=0，任意实数皆为解", "UNSUPPORTED", reason="逻辑正确；常量方程验证器UNKNOWN，不能由算术0的VERIFIED冒充方程认证"),
    C("后两种不是一次方程，只有a=0,b≠0才是一次", "DERIVED")],
"degenerate:b0": [C("a≠0,b=0仍二次，成为ax²+c=0", "DIRECT"), C("x²=-c/a"),
    C("-c/a>0时根为±√(-c/a)"), C("x²=4根为±2"), C("-c/a=0时x=0为二重根"),
    C("-c/a<0无实根"), C("Δ=-4ac与-c/a同号，三种分类一致"),
    C("y=ax²+c为抛物线，对称轴y轴", "UNSUPPORTED", reason="数学正确但可见摘录未提供函数图像性质"),
    C("方程根是抛物线与x轴交点横坐标", "UNSUPPORTED", reason="数学正确，资料未给函数零点定义"),
    C("正时两个交点、零时顶点在x轴、负时无交点", "UNSUPPORTED", reason="基于图像性质，不能混作当前证据原句"),
    C("b或c为0不会在a≠0前提下降次")],
"degenerate:c0": [C("c=0得ax²+bx=0，提取x得到x(ax+b)=0"), C("乘积为零至少一个因式为零", "UNSUPPORTED", reason="零积性质正确，但可见摘录未陈述"),
    C("根为0和-b/a，a≠0使分母有意义"), C("Δ=b²≥0，只有b=0时两根重合"),
    C("b=0时ax²+c=0，x²=-c/a"),
    C("现在没有一次项，不能套用提取x", "UNSUPPORTED", "AI_FALSE", "若同时c=0，则ax²=x(ax)仍可提x；是否可提公因式不由缺少一次项单独决定"),
    C("-c/a正、零、负分别两个相反根、二重零根、无实根"),
    C("b=c=0时唯一不同实根0，重数为2"),
    C("c=0,b≠0的0与-b/a一正一负（或一零一非零）", "UNSUPPORTED", "AI_FALSE", "零既非正也非负，括号中的或不能撤回错误；a=b=1,c=0得到0,-1"),
    C("b=0,c≠0时只能靠开平方", "UNSUPPORTED", "AI_FALSE", "仍可使用求根公式或判别式；有实根时可因式分解，‘只能’过强"),
    C("b=0,c≠0时a,c异号两实根，同号无实根"), C("c=0时Δ=b²，b≠0两不同根；b=0二重根")],
}
