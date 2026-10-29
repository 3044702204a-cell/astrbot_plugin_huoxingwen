"""流式补丁自测：不依赖 AstrBot 运行时，只验证 send_streaming 包装是否生效。

用法（在插件目录下）：
    set PYTHONPATH=E:\\AstrBot\\backend\\app
    E:\\AstrBot\\backend\\python\\python.exe tests\\test_stream_patch.py
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import HuoxingwenPlugin  # noqa: E402

from astrbot.api.message_components import Plain  # noqa: E402
from astrbot.core.message.message_event_result import MessageChain  # noqa: E402

from huoxing import to_martian  # noqa: E402


class FakeEvent:
    """最小可用的事件替身：只要有 set_extra / get_extra / get_message_type。"""

    def __init__(self) -> None:
        self._extras: dict[str, object] = {}

    def set_extra(self, key, value) -> None:
        self._extras[key] = value

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def get_message_type(self):
        return "friend"


class FakeEventSub(FakeEvent):
    """只覆写 send_streaming 的子类，模拟真实平台适配器。"""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    async def send_streaming(self, generator, use_fallback: bool = False) -> None:
        async for chunk in generator:
            self.sent.append(chunk.get_plain_text() if chunk.chain else "")


def make_plugin(**cfg) -> HuoxingwenPlugin:
    plugin = object.__new__(HuoxingwenPlugin)
    plugin.config = {
        "enabled": True,
        "mode": "huoxing",
        "only_llm": True,
        "probability": 100,
        "scope": "both",
        "protect_code": True,
        "protect_url": True,
        "protect_at": True,
        "decorate": False,
        "decoration_chars": "ゞ",
        **cfg,
    }
    plugin._rng = random.Random(0)
    plugin._session_state = {}
    plugin._state_path = None
    return plugin


async def _stream(texts: list[str]):
    for text in texts:
        yield MessageChain(chain=[Plain(text)])


def run_stream(plugin: HuoxingwenPlugin, event: FakeEvent, texts: list[str]) -> list[str]:
    class Sub(FakeEventSub):
        pass

    plugin._install_stream_hooks(Sub)
    ev = Sub()
    asyncio.run(ev.send_streaming(_stream(texts)))
    return ev.sent


def main() -> None:
    plugin = make_plugin()
    chunks = run_stream(plugin, FakeEvent(), ["我爱你", "今天天气不错"])
    assert chunks == ["莪嬡沵", "妗兲兲氣芣措"], chunks
    print("stream convert ->", chunks)

    # 重复安装不会叠加包装
    plugin._install_stream_hooks(FakeEventSub)
    again = run_stream(plugin, FakeEvent(), ["我爱你"])
    assert again == ["莪嬡沵"], again
    print("idempotent install ->", again)

    # 插件重载后（新实例）要换成新实例的包装，配置才会跟着新实例走
    reloaded = make_plugin(mode="traditional")
    trad = run_stream(reloaded, FakeEvent(), ["我爱你"])
    assert trad == [to_martian("我爱你", mode="traditional")], trad
    print("reloaded instance ->", trad)

    # 关掉会话后原样透传
    plugin._session_state[""] = False
    raw = run_stream(plugin, FakeEvent(), ["我爱你"])
    assert raw == ["我爱你"], raw
    print("session off ->", raw)

    # probability=0 时不转换
    plugin2 = make_plugin(probability=0)
    passthrough = run_stream(plugin2, FakeEvent(), ["我爱你"])
    assert passthrough == ["我爱你"], passthrough
    print("probability 0 ->", passthrough)

    print("ok")


if __name__ == "__main__":
    main()
