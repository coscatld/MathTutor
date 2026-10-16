"""Import this file in My Plugins, enable it, then send /double 21."""


def run(request: dict) -> dict:
    text = request.get("text", "").strip()
    try:
        value = int(text)
    except ValueError:
        return {"text": "请在命令后输入一个整数，例如 /double 21。"}
    if abs(value) > 10**12:
        return {"text": "示例只处理绝对值不超过一万亿的整数。"}
    return {"text": f"{value} 的两倍是 {value * 2}。", "data": {"input": value, "result": value * 2}}
