"""Versioned curriculum graph: fine skills, prerequisite DAG and related edges.

Family IDs remain compatibility keys, never per-student mastery labels.
Unknown families are deliberately OOV, not assigned a made-up skill.
"""
from dataclasses import asdict, dataclass, replace

GRAPH_VERSION = "mt-skills-v2"
# Existing skill identities / event labels do not change. This separately
# versions the newly introduced, narrower instructional step mappings.
STEP_MAPPING_VERSION = "mt-step-skills-v1"


@dataclass(frozen=True)
class DiagnosticItem:
    problem_text: str
    prompt: str
    verifier_family: str
    assessment_scope: str
    interpretation_limit: str


@dataclass(frozen=True)
class Skill:
    skill_id: str
    label: str
    prerequisites: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    definition: str = ""
    common_errors: tuple[str, ...] = ()
    supported_families: tuple[str, ...] = ()
    diagnostics: tuple[DiagnosticItem, ...] = ()
    version: str = GRAPH_VERSION


SKILLS = {s.skill_id: s for s in (
    Skill("signed_operations", "有理数与符号运算", aliases=("负数", "正负", "有理数", "符号")),
    Skill("fraction_operations", "分数运算", ("signed_operations",), ("通分", "约分", "分母", "分数")),
    Skill("distributive_law", "分配律与去括号", ("signed_operations",), ("分配律", "展开", "去括号")),
    Skill("combine_like_terms", "合并同类项", ("distributive_law",), ("同类项", "合并", "系数")),
    Skill("equality_preservation", "等式两边同做运算", ("signed_operations",), ("等式", "两边", "平衡", "等价", "移项")),
    Skill("linear_isolation", "一元一次方程隔离未知数", ("equality_preservation", "combine_like_terms"), ("一次方程", "未知数", "系数化", "隔离")),
    Skill("substitution_check", "代回原条件检验", ("equality_preservation",), ("代入", "检验", "验算", "成立")),
    Skill("factorisation", "二次式因式分解", ("combine_like_terms",), ("因式", "分解", "十字", "配方")),
    Skill("quadratic_discriminant", "判别式与实根条件", ("signed_operations",), ("判别式", "实根", "无实数解", "根号")),
    Skill("quadratic_roots", "求齐二次方程的根", ("factorisation", "quadratic_discriminant"), ("二次方程", "求根公式", "漏根", "重根", "韦达")),
    Skill("system_elimination", "方程组消元", ("equality_preservation", "combine_like_terms"), ("消元", "加减法", "消去", "联立"), ("system_substitution",)),
    Skill("system_substitution", "方程组代入", ("linear_isolation",), ("代入法", "表达式代入", "二元"), ("system_elimination",)),
    Skill("system_completeness", "方程组完整解与原式检验", ("system_elimination", "substitution_check"), ("方程组", "两个未知数", "都满足")),
)}

FAMILY_SKILLS = {
    "arithmetic": ("signed_operations", "fraction_operations"),
    "polynomial": ("distributive_law", "combine_like_terms"),
    "linear": ("equality_preservation", "linear_isolation", "substitution_check"),
    "linear_inequality": ("equality_preservation", "linear_isolation"),
    "quadratic_inequality": ("factorisation", "quadratic_roots", "substitution_check"),
    "quadratic": ("factorisation", "quadratic_discriminant", "quadratic_roots", "substitution_check"),
    "linear_system": ("system_elimination", "system_substitution", "system_completeness"),
}

# Diagnostic tasks stay within the five existing verifier families. A correct
# whole-task answer does not prove a particular method or all prerequisite
# skills; method-specific evidence still requires a verified student step.
_METADATA = {
    "signed_operations": ("按运算顺序对有理数进行精确运算，并保持正负号正确。",
        ("减去负数仍按减法处理", "乘除结果符号错误"), ("arithmetic",),
        DiagnosticItem("-3+5", "计算 -3+5，说明结果的符号。", "arithmetic", "component",
                       "验证数值；自由解释单独记录，不自动判定解释正确。")),
    "fraction_operations": ("在非零分母条件下通分、约分，并完成分数四则运算。",
        ("相加时直接相加分母", "约分跨越加法项"), ("arithmetic",),
        DiagnosticItem("1/2+1/3", "计算 1/2+1/3，可写通分后的步骤。", "arithmetic", "component",
                       "最终数值正确不等于已经验证通分过程。")),
    "distributive_law": ("将括号外的因子乘到括号内每一项，正确处理负号。",
        ("因子只乘括号第一项", "负号没有作用于所有项"), ("polynomial", "linear", "linear_system"),
        DiagnosticItem("2(x+3)", "展开并化简 2(x+3)。", "polynomial", "component",
                       "检验代数等价；不能由一个答案推断所有分配律场景。")),
    "combine_like_terms": ("只合并字母及对应次数相同的项，对其系数求和。",
        ("不同次数的项相加合并", "合并时改变字母或指数"), ("polynomial", "linear", "quadratic", "linear_system"),
        DiagnosticItem("3x+2x", "合并 3x+2x 中的同类项。", "polynomial", "component",
                       "本题只检验同一次数同字母的局部合并。")),
    "equality_preservation": ("对等式两边同时进行相同的合法运算，保持原等式的解集。",
        ("只在等式一边加减", "除以零或未检查除数"), ("linear", "linear_system"),
        DiagnosticItem("x+3=7", "解 x+3=7；可以先写两边同时减去 3 的结果。", "linear", "joint_task",
                       "最终解只提供整题证据；等式性质须由对应变形单独验证。")),
    "linear_isolation": ("整理一次方程后，通过非零系数除法隔离未知数。",
        ("除以系数时只处理一边", "常数项未移走就直接除系数"), ("linear", "linear_system"),
        DiagnosticItem("2x=8", "求 2x=8 中的 x。", "linear", "component",
                       "只检验简单非零系数的隔离，不覆盖所有一次方程。")),
    "substitution_check": ("将候选值代入原始条件并计算，检查所有要求是否同时成立。",
        ("只检验变形后的一个条件", "代入负数时遗漏括号"), ("linear", "quadratic", "linear_system"),
        DiagnosticItem("2*2+3", "代入 x=2 后，2x+3 的数值是多少？计算 2*2+3。", "arithmetic", "component",
                       "仅检验代入后的数值计算，不证明已检查原题全部条件。")),
    "factorisation": ("把二次多项式改写成乘积，并通过展开核对等价性。",
        ("两个常数只满足积而不满足和", "零因子分支遗漏"), ("polynomial", "quadratic"),
        DiagnosticItem("x^2-5x+6=0", "解 x^2-5x+6=0，可尝试因式分解并写出过程。", "quadratic", "joint_task",
                       "现有根集验证不强制因式分解；只交根不能算作因式分解技能通过。")),
    "quadratic_discriminant": ("从标准二次式识别系数，计算 b²−4ac，并判断实根条件。",
        ("负的一次项系数代入时漏负号", "判别式小于零仍报实根"), ("quadratic",),
        DiagnosticItem("(-5)^2-4*1*6", "当 a=1、b=-5、c=6 时，计算判别式 (-5)^2-4*1*6。", "arithmetic", "component",
                       "公式和系数已经提供，只检验代入运算，不能声称学生会自主选取判别式。")),
    "quadratic_roots": ("在当前实数验证域内求出完整根集，保留双分支并排除不成立的根。",
        ("只给正根而漏负根", "把重根当作两个不同根"), ("quadratic",),
        DiagnosticItem("x^2-4=0", "求 x^2-4=0 的全部实数根。", "quadratic", "component",
                       "验证根集完整性；不据此推断采用了哪种求根方法。")),
    "system_elimination": ("将两个方程整体倍乘并线性组合，消去一个未知数。",
        ("倍乘时遗漏常数项", "相加后待消元系数没有抵消"), ("linear_system",),
        DiagnosticItem("2x+y=7;x-y=2", "解方程组 2x+y=7、x-y=2；可先写消去 y 后的等式。", "linear_system", "joint_task",
                       "完整解正确不证明用了消元法；需验证实际消元步骤。")),
    "system_substitution": ("从一个条件表达某未知量，代入另一条件，再求剩余未知量。",
        ("代入时只替换表达式一部分", "表达式代入时丢失括号或系数"), ("linear_system",),
        DiagnosticItem("x-y=2;x+y=4", "解 x-y=2、x+y=4，可将一个未知数的表达式代入另一式。", "linear_system", "joint_task",
                       "解集验证接受其他正确路线；未观察代入步骤时不认定代入法通过。")),
    "system_completeness": ("给出方程组要求的全部未知量，并使其同时满足两个原方程。",
        ("只求一个未知量就结束", "两个数分别来自不一致的条件"), ("linear_system",),
        DiagnosticItem("2x+y=7;x-y=2", "求两个未知数，并检验 2x+y=7 和 x-y=2 是否同时成立。", "linear_system", "joint_task",
                       "完整解可验证，检验过程是否由学生完成须另看实际步骤。")),
}
SKILLS = {key: replace(skill, definition=meta[0], common_errors=meta[1],
                      supported_families=meta[2], diagnostics=(meta[3],))
          for key, skill in SKILLS.items() for meta in (_METADATA[key],)}


def graph_edges():
    """Only prerequisite edges imply ordering; membership never propagates evidence."""
    edges = []
    for skill in SKILLS.values():
        edges.extend({"source": prerequisite, "target": skill.skill_id, "kind": "prerequisite"}
                     for prerequisite in skill.prerequisites)
        edges.extend({"source": skill.skill_id, "target": other, "kind": "related"}
                     for other in skill.related)
        edges.extend({"source": skill.skill_id, "target": f"family:{family}", "kind": "part_of"}
                     for family in skill.supported_families)
    return edges


def skill_details(skill_ids):
    return [asdict(SKILLS[key]) for key in dict.fromkeys(skill_ids) if key in SKILLS]


def _has_fraction(value):
    if isinstance(value, dict):
        if value.get("kind") == "div" or ("n" in value and isinstance(value.get("d"), int) and value["d"] != 1):
            return True
        return any(_has_fraction(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_fraction(item) for item in value)
    return False


def skills_for_solution_step(problem, step):
    """Describe an operation, never declare a student mastered it.

    Input is a server candidate step, not a free-form LLM label. Attestation is
    checked separately by ProblemContext. Unrecognized shapes remain unmapped.
    """
    family = problem.problem_type
    if family == "arithmetic" and "expr" in step and "value" in step:
        return ("fraction_operations",) if _has_fraction(step["expr"]) else ("signed_operations",)
    if family == "polynomial" and "expr" in step and "coeffs" in step:
        return ("distributive_law", "combine_like_terms")
    if family in {"linear", "linear_inequality"}:
        return {"subtract_term": ("equality_preservation",),
                "divide_all": ("equality_preservation", "linear_isolation")}.get(step.get("transform", {}).get("kind"), ())
    if family in {"quadratic", "quadratic_inequality"}:
        if "boundary_roots" in step:
            return ("substitution_check",)
        if "discriminant" in step and all(k in step for k in ("a", "b", "c")):
            return ("quadratic_discriminant",)
        if "roots" in step:
            return ("quadratic_roots",)
    if family == "linear_system":
        return {"eliminate": ("system_elimination", "equality_preservation"),
                "solve_variable": ("linear_isolation",),
                "back_substitution": ("system_substitution",),
                "substitution": ("system_completeness", "substitution_check")}.get(step.get("kind"), ())
    return ()


def skills_for_subgoal(problem, subgoal_id, candidate=None):
    """Instructional focus of each existing goal, not a required solution route."""
    if problem.problem_type == "arithmetic":
        fraction = _has_fraction(problem.normalized_ast)
        return {"plan": ("fraction_operations",) if fraction else ("signed_operations",),
                "answer": ("signed_operations", "fraction_operations") if fraction else ("signed_operations",)}.get(subgoal_id, ())
    return {
        "polynomial": {"expand": ("distributive_law",), "combine": ("combine_like_terms",)},
        "linear": {"balance": ("equality_preservation",), "isolate": ("linear_isolation", "substitution_check")},
        "linear_inequality": {"balance": ("equality_preservation",), "isolate": ("linear_isolation",)},
        "quadratic_inequality": {"roots": ("quadratic_roots",), "sign": ("substitution_check",)},
        "quadratic": {"method": ("quadratic_discriminant",), "roots": ("quadratic_roots", "substitution_check")},
        "linear_system": {"eliminate": ("system_elimination", "linear_isolation"),
                          "remaining": ("system_substitution", "system_completeness", "substitution_check"),
                          "solve_variable": ("linear_isolation",), "back_substitution": ("system_substitution",),
                          "check": ("system_completeness", "substitution_check")},
    }.get(problem.problem_type, {}).get(subgoal_id, ())


def validate_graph(skills=SKILLS):
    visiting, done = set(), set()
    def visit(key):
        if key not in skills:
            raise ValueError(f"unknown prerequisite: {key}")
        if key in visiting:
            raise ValueError("prerequisite cycle")
        if key in done:
            return
        visiting.add(key)
        for parent in skills[key].prerequisites:
            visit(parent)
        visiting.remove(key)
        done.add(key)
    for key in skills:
        if key != skills[key].skill_id:
            raise ValueError("skill identity mismatch")
        if any(other not in skills for other in skills[key].related):
            raise ValueError("unknown related skill")
        visit(key)
    return True


def skills_for_problem(problem):
    return FAMILY_SKILLS.get(problem.problem_type, ())


def related_question(text, problem):
    keys = set(skills_for_problem(problem))
    for key in tuple(keys):
        keys.update(SKILLS[key].prerequisites)
        keys.update(SKILLS[key].related)
    return any(word in text for key in keys for word in (*SKILLS[key].aliases, SKILLS[key].label))


validate_graph()
