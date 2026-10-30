"""未绑定调用自测：模拟插件以停用态加载后 handler 没有绑定实例的情况。

用法（在插件目录下）：
    set PYTHONPATH=E:\\AstrBot\\backend\\app
    E:\\AstrBot\\backend\\python\\python.exe tests\\test_unbound_call.py
"""

from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as plugin_module  # noqa: E402
from main import HuoxingwenPlugin  # noqa: E402

from astrbot.api.message_components import Plain  # noqa: E402
from astrbot.core.message.message_event_result import MessageChain  # noqa: E402


class FakeResult:
    def __init__(self, text: str) -> None:
        self.chain = [Plain(text)]

    def is_model_result(self) -> bool:
        return True


class FakeEvent:
    """够用的消息事件替身。"""

    def __init__(self, text: str = "我爱你") -> None:
        self.unified_msg_origin = "test:FriendMessage:1"
        self._result = FakeResult(text)
        self._extras: dict[str, object] = {}

    # AstrMessageEvent 的最小接口
    def set_extra(self, key, value) -> None:
        self._extras[key] = value

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def get_message_type(self):
        return "friend"

    def get_result(self):
        return self._result

    def get_message_str(self) -> str:
        return self._result.chain[0].text

    def plain_result(self, text: str):
        return ("plain", text)


class FakeMetadata:
    def __init__(self, instance) -> None:
        self.star_cls = instance


def make_plugin() -> HuoxingwenPlugin:
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
    }
    plugin._rng = random.Random(0)
    plugin._session_state = {}
    plugin._state_path = None
    return plugin


def test_no_instance_does_not_raise() -> None:
    """注册表里没有实例时，未绑定调用必须安静跳过而不是抛异常。"""
    plugin_module.star_map.pop(plugin_module.__name__, None)
    event = FakeEvent()
    # 关键：以「未绑定函数」的形式调用，第一个位置参数是 event
    asyncio.run(HuoxingwenPlugin.on_decorating_result(event))
    asyncio.run(HuoxingwenPlugin.install_stream_hook(event))
    assert event.get_result().chain[0].text == "我爱你"
    print("unbound without instance -> no crash")


def test_command_hint_without_instance() -> None:
    plugin_module.star_map.pop(plugin_module.__name__, None)
    event = FakeEvent()

    async def collect():
        return [chunk async for chunk in HuoxingwenPlugin.huoxing_switch(event, "")]

    chunks = asyncio.run(collect())
    assert chunks and chunks[0][0] == "plain", chunks
    assert "没有正确加载" in chunks[0][1], chunks
    print("unbound command ->", chunks[0][1])


def test_unbound_call_uses_live_instance() -> None:
    """注册表里有实例时，未绑定调用要自动取到实例并正常转换。"""
    plugin = make_plugin()
    plugin_module.star_map[plugin_module.__name__] = FakeMetadata(plugin)
    event = FakeEvent()
    asyncio.run(HuoxingwenPlugin.on_decorating_result(event))
    converted = event.get_result().chain[0].text
    assert converted != "我爱你", converted
    print("unbound with live instance ->", converted)

    plugin_module.star_map[plugin_module.__name__] = FakeMetadata(plugin)
    event2 = FakeEvent("今天天气不错")
    asyncio.run(HuoxingwenPlugin.on_decorating_result(event2))
    print("unbound with live instance ->", event2.get_result().chain[0].text)


def test_bound_call_still_works() -> None:
    """正常绑定路径不能被改坏。"""
    plugin = make_plugin()
    event = FakeEvent()
    asyncio.run(plugin.on_decorating_result(event))
    assert event.get_result().chain[0].text != "我爱你"
    print("bound call ->", event.get_result().chain[0].text)


def test_bind_handlers_is_idempotent() -> None:
    plugin = make_plugin()
    plugin._bind_handlers()  # 注册表为空时应安全返回
    plugin._bind_handlers()
    print("bind handlers idempotent -> ok")


def main() -> None:
    test_no_instance_does_not_raise()
    test_command_hint_without_instance()
    test_unbound_call_uses_live_instance()
    test_bound_call_still_works()
    test_bind_handlers_is_idempotent()
    print("ok")


if __name__ == "__main__":
    main()
