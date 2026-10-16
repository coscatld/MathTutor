"""Bundled examples registered by the host, never by imported Markdown."""
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field

from .registry import ExtensionManifest, ExtensionRegistry, StrictArguments
from .workspaces import register_workspace_tools


class LengthArguments(StrictArguments):
    value: str = Field(pattern=r"^\d{1,16}(?:\.\d{1,12})?$", max_length=30)
    from_unit: Literal["mm", "cm", "dm", "m", "km"]
    to_unit: Literal["mm", "cm", "dm", "m", "km"]


async def convert_length(args, context):
    factors = {"mm": Decimal("0.001"), "cm": Decimal("0.01"), "dm": Decimal("0.1"),
               "m": Decimal("1"), "km": Decimal("1000")}
    with localcontext() as precision:
        precision.prec = 50
        factor = factors[args.from_unit] / factors[args.to_unit]
        value = Decimal(args.value) * factor
    return {"input": {"value": args.value, "unit": args.from_unit},
            "output": {"value": format(value, "f"), "unit": args.to_unit},
            "conversion_factor": format(factor, "f")}


def default_registry(workspaces=None):
    registry = ExtensionRegistry()
    registry.register_tool(ExtensionManifest(id="mathtutor.length-conversion", version="1.0.0", kind="tool",
        name="长度单位换算", description="确定性换算非负十进制长度，支持 mm、cm、dm、m、km。value 使用十进制字符串，结果仅作为讲解参考，不证明学生掌握。"),
        name="ext_length_convert", input_model=LengthArguments, handler=convert_length, source="builtin")
    registry.register_skill(ExtensionManifest(id="mathtutor.stepwise-explanation", version="1.0.0",
        name="逐步讲解", description="用一个明确的小步骤和适用条件帮助学生继续思考，由应用启动配置显式启用。", kind="teaching-skill"),
        instructions="围绕学生当前疑点先解释一个关键联系，给出可执行的下一步；学生明确请求完整解答时完整回答。", source="builtin")
    if workspaces is not None:
        register_workspace_tools(registry, workspaces)
    return registry
