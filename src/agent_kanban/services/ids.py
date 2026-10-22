"""id 归一（响应边界）：Uuid(as_uuid=False) 读回 36-char 带连字符，统一为
32-hex 无连字符——与写路径内存实例/create 响应及事件 payload 引用一致。"""


def norm_id(value: object) -> str:
    return str(value).replace("-", "")
