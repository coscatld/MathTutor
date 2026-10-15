"""Verified prerequisite exercises for questions outside the teaching domain.

The suggestion is a separate exercise, never a solution to the original task.
Selecting it still requires the student's explicit new-problem command.
"""
from __future__ import annotations

import re


UNVERIFIED_NOTICE = "> 本段讲解未经逐句数学核验。"


def recovery_candidate(text: str, *, mathematical: bool = False) -> tuple[str, str] | None:
    """Choose a nearby skill, without inventing a translation of a word task."""
    source = str(text or "").strip()
    if not source:
        return None
    # A conceptual explanation is not an unfinished homework task. Avoid
    # creating an unrelated equation merely because this used the math route.
    concept = re.match(r"^(?:请)?(?:解释|讲讲|讲解|说明|介绍|为什么|什么是)", source)
    concrete_task = re.search(r"求解|计算|化简|证明|解(?:不等式|方程)|求(?:值|根|面积|周长|长度|角)", source)
    if concept and not concrete_task:
        return None
    if re.search(r"函数|零点|单调|奇偶|指数|对数|分段|数列|导数|圆锥曲线|椭圆|双曲线|三角函数|概率|统计|[fghFGH]\s*\(|(?:\d|e)\s*\^\s*[A-Za-z]", source) and not re.search(r"补基础|基础练习|先练基础", source):
        # Keep a high-school task intact. Lack of a local solver is not
        # evidence that the learner needs elementary equation practice.
        return None
    task = bool(re.search(r"求|计算|证明|(?<!讲)解(?!释|读|说)|化简|多少|几[元米个岁]|应用题|题目", source))
    if not mathematical and not task:
        return None
    if re.search(r"不等式|[<>≤≥]", source):
        return "3x-4=11", "先练整理等式与移项；原题的不等号方向和取值范围仍需另行核对。"
    if re.search(r"直角|勾股|斜边", source):
        return "x^2-25=0", "先练平方方程的求根；原题中的长度条件仍需单独核对。"
    if re.search(r"三角形|内角|外角|角度|∠", source):
        return "180-50-60", "先练角度题常用的加减计算；这道练习不代表原题的几何条件已经核验。"
    if re.search(r"几何|面积|周长|长方形|正方形|圆|平行|垂直", source):
        return "2*(x+3)=18", "先练周长和数量关系常用的等式整理；没有把这道练习当成原题的解答。"
    if re.search(r"参数|含参|[abc]\s*=?\s*0|[abc]x(?:\^?2|²)", source):
        return "x^2-5x+6=0", "先练系数已确定的二次方程；原题的参数分类讨论仍未核验。"
    if re.search(r"函数|y\s*=|f\s*\(", source):
        return "2x+3=11", "先练给定函数值后求未知数的等式；图像和函数性质仍需另行核对。"
    if re.search(r"分式|分母|/[^\s]*[a-zA-Z]|[a-zA-Z][^\s]*/", source):
        return "3x-4=11", "先练去分母后常用的等式整理；原题的分母非零条件仍需单独核对。"
    if re.search(r"二次|平方|\^2|²", source):
        return "x^2-5x+6=0", "先练能逐步检查的二次方程求根；原题还保留在对话中。"
    if re.search(r"买|每|总共|一共|路程|速度|小时|年龄|应用题", source):
        return "3x+2=11", "先练应用题列式后的两步方程；这道练习没有替原题补造条件。"
    if mathematical or re.search(r"方程|数学|代数|计算|求解|几何|证明", source):
        return "3x+2=11", "先练一题能逐步检查的两步方程；原题还保留在对话中。"
    return None


def mark_unverified(text: str) -> str:
    """An application disclosure survives model instructions and history replay."""
    return text if text.startswith(UNVERIFIED_NOTICE) else f"{UNVERIFIED_NOTICE}\n\n{text}"


def simple_greeting(request: str, response: str) -> bool:
    """Only an ordinary short greeting needs no mathematical disclosure."""
    greeting = re.fullmatch(r"(?:你好|您好|嗨|哈喽|hello|hi)[\s。.!！?？]*", request.strip(), re.I)
    math_content = re.search(r"[0-9=+*/^<>≤≥\\]|计算|运算|方程|等式|未知数|同类项|函数|几何|三角|分母|分式|代数|平方|判别|移项|圆周|面积|周长|定理|概率", response)
    return bool(greeting and len(response) <= 100 and not math_content)
