/** Raw ToolDefinition subset; no runtime Cordis dependency is imported. */
export const name = "harness-double";
export const inject = ["tools"];

export function apply(ctx, config) {
  ctx.tools.register({
    name: "double",
    description: "Multiply a number by two.",
    parameters: {
      type: "object",
      properties: { value: { type: "number" } },
      required: ["value"],
      additionalProperties: false,
    },
    output: {
      schema: { type: "number" },
      render: (_args, value) => [{ type: "text", text: String(value) }],
    },
    execute(args, exec) {
      if (exec.signal.aborted) throw new Error("Cancelled");
      return args.value * 2;
    },
  });
}
