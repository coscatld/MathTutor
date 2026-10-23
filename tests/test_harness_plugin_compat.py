"""Real Harness-style source adaptation through the existing trusted runtime."""
import json
from types import SimpleNamespace

import pytest

from mathtutor.extensions import developer
from mathtutor.extensions.code_plugins import CODE_PERMISSION, CodePluginRuntime, parse_code_upload
from mathtutor.extensions.community_plugins import CommunityPluginService
from mathtutor.extensions.harness_compat import adapt
from mathtutor.extensions.registry import ExtensionError
from test_code_plugins import native_node


SOURCE = '''export const name = "example";
export const inject = ["tools"];
export function apply(ctx, config) {
  ctx.tools.register({
    name: "double", description: "Multiply a number",
    parameters: {type: "object", properties: {value: {type: "number"}}, required: ["value"], additionalProperties: false},
    output: {schema: {type: "number"}, render: (_args, value) => [{type: "text", text: String(value)}]},
    execute: (args, exec) => { if (exec.signal.aborted) throw new Error("aborted"); return args.value * (config.factor || 2); }
  });
}
'''


def adapted(tmp_path, source=SOURCE):
    directory = tmp_path / "author"
    assert developer.main(["init", str(directory), "--runtime", "typescript", "--id", "example.harness",
        "--name", "Harness subset", "--author", "Test", "--license", "MIT", "--command", "double"]) == 0
    (directory / "main.ts").write_text(source, encoding="utf-8")
    return parse_code_upload(adapt(directory, [], "double"), "adapted.zip")


@pytest.mark.asyncio
async def test_adapted_apply_tool_requires_consent_and_executes_with_reference_result(tmp_path, native_node):
    package = adapted(tmp_path)
    service = CommunityPluginService(state=SimpleNamespace(), storage_root=tmp_path / "installed")
    row = service.import_package("alice", package.model_dump())
    assert row["enabled"] is False
    with pytest.raises(ExtensionError):
        await service.run_slash("alice", "double", '{"value":21}', operation_id="denied")
    service.set_enabled("alice", package.id, enabled=True, consent_permissions=[CODE_PERMISSION])
    service.configure("alice", package.id, {"factor": 3})
    result = await service.run_slash("alice", "double", '{"value":14}', operation_id="once")
    assert result["data"] == {"text": "42", "data": 42, "tool": "double", "compatibility": "harness-tool-subset-v1"}
    assert result["authority"] == "reference_only" and result["sandboxed"] is False
    assert await service.run_slash("alice", "double", '{"value":14}', operation_id="once") == result
    assert service.commands("bob") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ['{}', '{"value":"21"}', '{"value":21,"extra":true}', '[]'])
async def test_invalid_schema_arguments_fail(tmp_path, native_node, text):
    package = adapted(tmp_path)
    with pytest.raises(ExtensionError):
        await CodePluginRuntime(tmp_path / "runs")._execute(package, {"text": text, "config": {}})


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [
    SOURCE.replace('ctx.tools.register({', 'ctx.on("event", () => {}); ctx.tools.register({'),
    SOURCE.replace('type: "number"}', 'type: "number", minimum: 0}', 1),
    SOURCE.replace('return args.value * (config.factor || 2)', 'return "wrong output type"'),
    SOURCE.replace('export const inject = ["tools"]', 'export const inject = ["tools", "llm"]'),
    SOURCE.replace('ctx.tools.register({', 'const definition = {').replace('  });',
        '  }; ctx.tools.register(definition); definition.parameters.properties.value.minimum = 100;'),
    SOURCE.replace('ctx.tools.register({', 'const definition = {').replace('  });',
        '  }; ctx.tools.register(definition); definition.execute = () => { definition.output.schema.minimum = 100; return 42; };'),
])
async def test_unsupported_context_schema_and_output_fail_closed(tmp_path, native_node, source):
    package = adapted(tmp_path, source)
    with pytest.raises(ExtensionError):
        await CodePluginRuntime(tmp_path / "runs")._execute(package, {"text": '{"value":21}', "config": {}})


def test_adaptation_is_static_and_cli_output_is_a_normal_importable_package(tmp_path):
    adapted(tmp_path, 'throw new Error("must not execute at build");\n' + SOURCE)
    output = tmp_path / "adapted.zip"
    assert developer.main(["adapt-harness", str(tmp_path / "author"), "--tool", "double", "-o", str(output)]) == 0
    package = parse_code_upload(output.read_bytes(), output.name)
    assert package.entrypoint == "mathtutor-harness-entry.ts"
    assert package.required_permissions == [CODE_PERMISSION]
    assert developer.main(["adapt-harness", str(tmp_path / "author"), "--tool", "double", "-o", str(output)]) == 2


@pytest.mark.asyncio
async def test_legal_entrypoint_containing_template_token_executes(tmp_path, native_node):
    adapted(tmp_path)
    directory = tmp_path / "author"
    (directory / "main.ts").rename(directory / "__TOOL__.ts")
    manifest_path = directory / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entrypoint"] = "__TOOL__.ts"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = parse_code_upload(adapt(directory, [], "double"), "adapted.zip")
    result = await CodePluginRuntime(tmp_path / "runs")._execute(package, {"text": '{"value":21}', "config": {}})
    assert result["data"] == 42
