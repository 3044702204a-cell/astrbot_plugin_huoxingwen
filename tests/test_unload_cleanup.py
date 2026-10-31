"""停用 / 卸载后的收尾自测。

覆盖「插件关掉了、甚至删掉了，回复还是火星文」这条问题链：
send_streaming 的猴子补丁不在 handler 注册表里，插件不主动撤，它会一直活到重启。
这里逐个验证停用、卸载、重载、总开关关闭、terminate 五种情况下都不再转换，
并且补丁会回到原函数。

用法（在插件目录下）：
    set PYTHONPATH=E:\\AstrBot\\backend\\app
    E:\\AstrBot\\backend\\python\\python.exe tests\\test_unload_cleanup.py
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


class FakeMetadata:
    """star_map 里的那份插件元数据替身。"""

    def __init__(self, instance, activated: bool = True) -> None:
        self.star_cls = instance
        self.activated = activated
        self.name = "astrbot_plugin_huoxingwen"
        self.module_path = plugin_module.PLUGIN_MODULE


class FakeEvent:
    def __init__(self) -> None:
        self.unified_msg_origin = "test:FriendMessage:1"
        self._extras: dict[str, object] = {}
        self._result = FakeResult("我爱你")

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


class FakeResult:
    def __init__(self, text: str) -> None:
        self.chain = [Plain(text)]

    def is_model_result(self) -> bool:
        return True


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


def register(plugin, activated: bool = True) -> None:
    plugin_module.star_map[plugin_module.PLUGIN_MODULE] = FakeMetadata(plugin, activated)


def unregister(keep_others: bool = True) -> None:
    plugin_module.star_map.pop(plugin_module.PLUGIN_MODULE, None)
    if keep_others:
        # 注册表里还有别的插件：说明框架在跑，只是本插件被卸了
        plugin_module.star_map["some_other_plugin.main"] = FakeMetadata(None)


async def _stream(texts: list[str]):
    for text in texts:
        yield MessageChain(chain=[Plain(text)])


def stream_through(plugin, event_cls: type, texts: list[str]) -> list[str]:
    """按真实流程跑一遍：装补丁 -> 平台 send_streaming 消费分片。"""
    plugin._install_stream_hooks(event_cls)
    return run_stream(event_cls, texts)


def run_stream(event_cls: type, texts: list[str]) -> list[str]:
    """不装补丁，直接让平台实现消费分片（用来验证补丁确实被撤掉了）。"""
    event = event_cls()
    asyncio.run(event.send_streaming(_stream(texts)))
    return event.sent


def new_event_cls(name: str) -> type:
    async def send_streaming(self, generator, use_fallback: bool = False):
        async for chunk in generator:
            self.sent.append(chunk.get_plain_text() if chunk.chain else "")

    cls = type(name, (FakeEvent,), {"sent": None})
    cls.send_streaming = send_streaming

    def __init__(self):
        FakeEvent.__init__(self)
        self.sent = []

    cls.__init__ = __init__
    return cls


def test_disable_stops_conversion() -> None:
    """停用后：流式不再转换，包装被摘回原函数。"""
    plugin = make_plugin()
    event_cls = new_event_cls("DisableEvent")
    original = event_cls.__dict__["send_streaming"]
    register(plugin, activated=True)

    assert stream_through(plugin, event_cls, ["我爱你"]) == ["莪嬡沵"]

    register(plugin, activated=False)  # WebUI 里点停用
    assert stream_through(plugin, event_cls, ["我爱你"]) == ["我爱你"]
    assert event_cls.__dict__["send_streaming"] is original, event_cls.__dict__
    print("disable ->", "passthrough, patch reverted")


def test_uninstall_stops_conversion() -> None:
    """卸载后（注册表里已经没有本插件）：不再转换。"""
    plugin = make_plugin()
    event_cls = new_event_cls("UninstallEvent")
    original = event_cls.__dict__["send_streaming"]
    register(plugin)
    assert stream_through(plugin, event_cls, ["我爱你"]) == ["莪嬡沵"]

    unregister()
    assert plugin.is_active(FakeEvent()) is False
    assert stream_through(plugin, event_cls, ["我爱你"]) == ["我爱你"]
    assert event_cls.__dict__["send_streaming"] is original
    print("uninstall ->", "passthrough, patch reverted")


def test_reload_drops_old_instance() -> None:
    """热重载后：旧实例的补丁失效，新实例照常转换。"""
    old = make_plugin()
    event_cls = new_event_cls("ReloadEvent")
    register(old)
    assert stream_through(old, event_cls, ["我爱你"]) == ["莪嬡沵"]

    new = make_plugin(mode="traditional")
    register(new)  # 框架把 star_cls 换成了新实例，旧实例没收到 terminate 也不会再动手
    assert old.is_active(FakeEvent()) is False
    assert stream_through(old, event_cls, ["我爱你"]) == ["我爱你"]

    trick = plugin_module.to_martian("我爱你", mode="traditional")
    assert stream_through(new, event_cls, ["我爱你"]) == [trick]
    print("reload ->", "old instance retired, new instance ->", trick)


def test_config_switch_off_installs_nothing() -> None:
    """总开关关掉后连补丁都不该装。"""
    plugin = make_plugin(enabled=False)
    event_cls = new_event_cls("ConfigOffEvent")
    original = event_cls.__dict__["send_streaming"]
    register(plugin)

    asyncio.run(plugin.install_stream_hook(FakeEvent()))
    assert event_cls.__dict__["send_streaming"] is original
    assert stream_through(plugin, event_cls, ["我爱你"]) == ["我爱你"]
    print("enabled=false ->", "no patch, passthrough")


def test_terminate_reverts_patch() -> None:
    """terminate() 要自己把补丁撤干净，不等框架来收。"""
    plugin = make_plugin()
    event_cls = new_event_cls("TerminateEvent")
    original = event_cls.__dict__["send_streaming"]
    register(plugin)
    assert stream_through(plugin, event_cls, ["我爱你"]) == ["莪嬡沵"]

    asyncio.run(plugin.terminate())
    assert event_cls.__dict__["send_streaming"] is original
    assert run_stream(event_cls, ["我爱你"]) == ["我爱你"]
    print("terminate ->", "patch reverted")


def test_decorating_hook_respects_disable() -> None:
    """非流式的发送前钩子在停用后同样不转换。"""
    plugin = make_plugin()
    plugin._state_path = None
    register(plugin, activated=False)
    event = FakeEvent()
    asyncio.run(plugin.on_decorating_result(event))
    assert event.get_result().chain[0].text == "我爱你"

    register(plugin, activated=True)
    event = FakeEvent()
    asyncio.run(plugin.on_decorating_result(event))
    assert event.get_result().chain[0].text == "莪嬡沵"
    print("decorating hook ->", "off: raw, on: converted")


def test_stale_patch_from_dead_instance_is_swept() -> None:
    """上一版插件留下的包装（闭包里抓着死实例）要被顺手剥掉。"""
    dead = make_plugin()
    event_cls = new_event_cls("StaleEvent")
    original = event_cls.__dict__["send_streaming"]
    event_cls.send_streaming = dead._make_send_streaming(original)
    plugin_module._record_patch(event_cls, "send_streaming", original, dead)

    fresh = make_plugin()
    register(fresh)
    plugin_module._restore_patches(only_dead=True)
    assert event_cls.__dict__["send_streaming"] is original
    print("stale patch ->", "swept")


def main() -> None:
    test_disable_stops_conversion()
    test_uninstall_stops_conversion()
    test_reload_drops_old_instance()
    test_config_switch_off_installs_nothing()
    test_terminate_reverts_patch()
    test_decorating_hook_respects_disable()
    test_stale_patch_from_dead_instance_is_swept()
    print("ok")


if __name__ == "__main__":
    main()
