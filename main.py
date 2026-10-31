"""火星文转换插件。

把模型最终输出的文本整段转成火星文（或繁体字 / 混排）再发送。
码表与 huoxingwen.qianwanku.com 一致，另外支持代码块、链接、@ 的原样保留，
以及可选的火星文装饰符号。
"""

from __future__ import annotations

import functools
import json
import random
import time
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.platform import MessageType
from astrbot.api.star import Context, Star, StarTools

try:
    from .huoxing import DEFAULT_DECORATIONS, MODE_LABELS, MODES, to_martian
except ImportError:  # pragma: no cover
    from huoxing import DEFAULT_DECORATIONS, MODE_LABELS, MODES, to_martian

# 插件注册表。仅用于兜底：AstrBot 在以「停用态」加载插件时不会实例化插件类，
# 于是本插件注册的 handler 会保持未绑定状态，被调用时 self 收到的其实是 event。
try:
    from astrbot.core.star.star import star_map
    from astrbot.core.star.star_handler import star_handlers_registry
except Exception:  # pragma: no cover
    star_map = None
    star_handlers_registry = None

PLUGIN_NAME = "astrbot_plugin_huoxingwen"
PLUGIN_MODULE = __name__
"""主模块的完整模块路径，同时也是 star_map 里登记的键。"""

STATE_FILE = "session_state.json"

ON_WORDS = {"开", "开启", "on", "1", "true", "启用"}
OFF_WORDS = {"关", "关闭", "off", "0", "false", "停用"}

_UNBOUND_WARNED = False


def _warn_unbound_once() -> None:
    """未绑定时只提示一次，避免每条消息都刷日志。"""
    global _UNBOUND_WARNED
    if _UNBOUND_WARNED:
        return
    _UNBOUND_WARNED = True
    logger.error(
        "[火星文] 插件实例缺失：插件是以停用状态被加载的，框架没有把 handler "
        "绑定到实例上。请在 WebUI 里重新启用本插件（必要时重启 AstrBot）。",
    )


def _live_instance() -> "HuoxingwenPlugin | None":
    """取当前进程里真正的插件实例。"""
    if not star_map:
        return None
    metadata = star_map.get(PLUGIN_MODULE)
    instance = getattr(metadata, "star_cls", None) if metadata is not None else None
    return instance if isinstance(instance, HuoxingwenPlugin) else None


# --------------------------------------------------------------------------- 补丁台账
# 打在框架类上的 send_streaming 包装不在 handler 注册表里，框架停用/卸载插件时
# 如果没有回滚干净，包装（以及闭包里抓着的旧实例）会一直活到进程重启，
# 表现就是「插件已经关了/删了，回复还是火星文」。这里自己记一份台账，按记录精确回滚。
_CLASS_PATCHES: list[tuple[type, str, Any, Any]] = []

# 插件自己的源文件。被手动删掉目录时靠它发现，最多 2 秒 stat 一次。
_PLUGIN_FILE = Path(__file__).resolve()
_FILE_CHECK_INTERVAL = 2.0
_file_probe: dict[str, Any] = {"checked_at": 0.0, "present": True}


def _peel_wrappers(func: Any) -> Any:
    """剥掉一个函数上叠加的所有 __wrapped__ 包装，返回最底层的原函数。"""
    seen: set[int] = set()
    current = func
    while True:
        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is None or id(wrapped) in seen:
            return current
        seen.add(id(current))
        current = wrapped


def _record_patch(cls: type, attr: str, original: Any, owner: Any) -> None:
    _CLASS_PATCHES[:] = [
        item
        for item in _CLASS_PATCHES
        if not (item[0] is cls and item[1] == attr and item[3] is owner)
    ]
    _CLASS_PATCHES.append((cls, attr, original, owner))


def _instance_alive(instance: Any) -> bool:
    """这个插件实例是否仍然是「当前有效」的那一份。"""
    if instance is None:
        return False
    try:
        if not star_map:
            # 注册表是空的：框架还没跑到这一步（或离线自测），不做判断。
            return True
        metadata = star_map.get(PLUGIN_MODULE)
    except Exception:
        return True
    if metadata is None:
        # 注册表里已经有别的插件，却没有本插件：已被卸载。
        return False
    if not getattr(metadata, "activated", True):
        return False
    current = getattr(metadata, "star_cls", None)
    if current is None:
        # 只有「以停用态加载」才会走到这里，上面的 activated 已经挡过一遍。
        return True
    # 重载之后 star_cls 是新实例，旧实例不能再改文本。
    return current is instance


def _plugin_files_present() -> bool:
    """插件源文件还在不在（防手动删目录后进程里残留）。"""
    now = time.monotonic()
    if now - _file_probe["checked_at"] < _FILE_CHECK_INTERVAL:
        return bool(_file_probe["present"])
    _file_probe["checked_at"] = now
    try:
        _file_probe["present"] = _PLUGIN_FILE.is_file()
    except OSError:
        _file_probe["present"] = True
    return bool(_file_probe["present"])


def _restore_patches(owner: Any = None, *, only_dead: bool = False) -> int:
    """把本插件打在类上的补丁换回原函数，返回回滚数量。

    owner 给定时只回滚这个实例装的补丁；only_dead=True 时只回滚那些
    「装的实例已经不是当前有效实例」的补丁（重载后清旧账用）。
    """
    restored = 0
    keep: list[tuple[type, str, Any, Any]] = []
    for cls, attr, original, patch_owner in _CLASS_PATCHES:
        if owner is not None and patch_owner is not owner:
            keep.append((cls, attr, original, patch_owner))
            continue
        if only_dead and _instance_alive(patch_owner):
            keep.append((cls, attr, original, patch_owner))
            continue
        current = cls.__dict__.get(attr)
        # 只撤自己的包装，别把别人后装的补丁一起抹了
        if getattr(current, "_huoxing_owner", None) is patch_owner:
            try:
                setattr(cls, attr, original)
                restored += 1
            except (AttributeError, TypeError):
                pass
    _CLASS_PATCHES[:] = keep
    return restored


def _looks_like_event(obj) -> bool:
    """判断某个对象是不是消息事件（含测试替身这类鸭子类型实现）。"""
    if isinstance(obj, AstrMessageEvent):
        return True
    return (
        obj is not None
        and not isinstance(obj, Star)
        and hasattr(obj, "get_extra")
        and hasattr(obj, "get_message_type")
    )


def _unpack_unbound(plugin, event, action=None):
    """归一化 handler 调用形式，返回 (plugin, event, action)。

    正常情况框架传入的是已绑定实例（plugin 是插件、event 是事件）。
    若插件以停用态被加载，注册表里留下的是未绑定函数，框架仍然是
    ``handler(event, **params)``：此时 self 收到的是 event，其余位置参数整体错位一格。
    这里把它们挪回原位。
    """
    if not _looks_like_event(plugin):
        return plugin, event, action
    real_event = event if _looks_like_event(event) else plugin
    if isinstance(event, str) and not action:
        action = event
    return _live_instance(), real_event, action


def _resolve_self(plugin, event):
    """只关心 (插件实例, 事件) 的归一化入口。"""
    plugin, event, _ = _unpack_unbound(plugin, event, None)
    return plugin, event


class HuoxingwenPlugin(Star):
    """把模型回复整段转成火星文再发出去。"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config if config is not None else {}
        self._rng = random.Random()
        self._state_path = self._resolve_state_path()
        self._session_state: dict[str, bool] = self._load_state()

    # ------------------------------------------------------------------ 配置/状态
    def _cfg(self, key: str, default: Any = None) -> Any:
        try:
            value = self.config.get(key, default)
        except Exception:
            return default
        return default if value is None else value

    def _resolve_state_path(self) -> Path | None:
        try:
            data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir / STATE_FILE
        except Exception:
            logger.warning("[火星文] 无法获取插件数据目录，会话开关将不会持久化。")
            return None

    def _load_state(self) -> dict[str, bool]:
        if self._state_path is None or not self._state_path.exists():
            return {}
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            return {str(k): bool(v) for k, v in raw.items()}
        except Exception:
            logger.warning("[火星文] 会话开关文件解析失败，已忽略。")
            return {}

    def _save_state(self) -> None:
        """把会话开关落盘。

        写之前先读一遍磁盘再做合并：热重载会先走 terminate()，如果直接整份覆盖，
        其它实例（或手动改过的开关）写进去的内容会被内存里的旧快照冲掉。
        """
        if self._state_path is None:
            return
        try:
            merged: dict[str, bool] = {}
            if self._state_path.exists():
                try:
                    raw = json.loads(self._state_path.read_text(encoding="utf-8"))
                    merged = {str(k): bool(v) for k, v in raw.items()}
                except Exception:
                    merged = {}
            merged.update(self._session_state)
            self._state_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("[火星文] 会话开关保存失败。")

    def _session_key(self, event: AstrMessageEvent) -> str:
        return getattr(event, "unified_msg_origin", "") or ""

    def _scope_ok(self, event: AstrMessageEvent) -> bool:
        scope = str(self._cfg("scope", "both"))
        if scope == "both":
            return True
        try:
            message_type = event.get_message_type()
        except Exception:
            return True
        if scope == "group":
            return message_type == MessageType.GROUP_MESSAGE
        if scope == "private":
            return message_type == MessageType.FRIEND_MESSAGE
        return True

    def _alive(self) -> bool:
        """插件是否还在岗：没停用、没卸载、没被新实例替换、源文件还在。"""
        return _instance_alive(self) and _plugin_files_present()

    def _enabled_for(self, event: AstrMessageEvent) -> bool:
        """配置与会话开关是否允许转换（不掷概率）。"""
        if not bool(self._cfg("enabled", True)):
            return False
        flag = self._session_state.get(self._session_key(event))
        if flag is not None:
            return flag
        return self._scope_ok(event)

    def is_active(self, event: AstrMessageEvent) -> bool:
        """当前会话是否需要转换。"""
        if not self._alive():
            return False
        return self._enabled_for(event)

    # ------------------------------------------------------------------ 生命周期
    async def initialize(self) -> None:
        """插件加载完成后，把本插件的 handler 绑到这一份实例上。

        框架在插件「停用态加载」或走旧版加载分支时会漏掉绑定，导致每次调用都
        把 event 当 self 传进来。这里补一次，绑定失败也不影响其余逻辑。
        """
        self._bind_handlers()

    def _bind_handlers(self) -> None:
        if star_handlers_registry is None:
            return
        module_path = PLUGIN_MODULE
        try:
            handlers = star_handlers_registry.get_handlers_by_module_name(module_path)
        except Exception:
            return
        for handler in handlers:
            current = handler.handler
            if (
                isinstance(current, functools.partial)
                and current.args
                and current.args[0] is self
            ):
                continue
            raw = current.func if isinstance(current, functools.partial) else current
            handler.handler = functools.partial(raw, self)

    def _unbind_handlers(self) -> None:
        """把自己绑上去的 handler 解回裸函数，别让注册表一直攥着旧实例。"""
        if star_handlers_registry is None:
            return
        try:
            handlers = star_handlers_registry.get_handlers_by_module_name(
                PLUGIN_MODULE,
            )
        except Exception:
            return
        for handler in handlers:
            current = handler.handler
            if (
                isinstance(current, functools.partial)
                and current.args
                and current.args[0] is self
            ):
                handler.handler = current.func

    # ------------------------------------------------------------------ 转换
    def _convert(self, text: str, *, decorate: bool | None = None) -> str:
        use_decorate = (
            bool(self._cfg("decorate", False)) if decorate is None else bool(decorate)
        )
        return to_martian(
            text,
            mode=str(self._cfg("mode", "huoxing")),
            protect_code=bool(self._cfg("protect_code", True)),
            protect_url=bool(self._cfg("protect_url", True)),
            protect_at=bool(self._cfg("protect_at", True)),
            decorate=use_decorate,
            decoration_chars=str(self._cfg("decoration_chars", DEFAULT_DECORATIONS)),
            rng=self._rng,
        )

    def _roll(self) -> bool:
        try:
            probability = int(self._cfg("probability", 100))
        except Exception:
            probability = 100
        probability = max(0, min(100, probability))
        if probability >= 100:
            return True
        if probability <= 0:
            return False
        return self._rng.randint(1, 100) <= probability

    def _convert_chain_inplace(self, chain, *, decorate: bool | None = None) -> int:
        converted = 0
        for comp in chain:
            if not isinstance(comp, Plain):
                continue
            text = getattr(comp, "text", "") or ""
            if not text.strip():
                continue
            new_text = self._convert(text, decorate=decorate)
            if new_text != text:
                comp.text = new_text
                converted += 1
        return converted

    @filter.on_decorating_result(priority=100)
    async def on_decorating_result(self, event: AstrMessageEvent | None = None) -> None:
        """发送前把结果链里的纯文本段换成火星文。"""
        self, event = _resolve_self(self, event)
        if self is None or event is None:
            _warn_unbound_once()
            return
        try:
            if not self._alive():
                # 已经停用/卸载了：把之前装的包装摘干净，这条回复原样发出去
                _restore_patches()
                return
            if event.get_extra("_huoxing_skip", False):
                return
            if event.get_extra("_huoxing_stream", False):
                # 流式输出已经在 send_streaming 补丁里逐片转换，避免二次转换
                return
            if not self.is_active(event):
                return
            result = event.get_result()
            if result is None or not result.chain:
                return
            if bool(self._cfg("only_llm", True)) and not result.is_model_result():
                return
            if not self._roll():
                return
            if self._convert_chain_inplace(result.chain):
                logger.debug("[火星文] 已转换当前回复。")
        except Exception:
            logger.exception("[火星文] 转换回复时出错，已跳过本次转换。")

    @filter.on_llm_request()
    async def install_stream_hook(self, event: AstrMessageEvent | None = None) -> None:
        """真正调用模型前，给当前平台的事件类装好流式转换钩子。

        流式输出时 AstrBot 会把分片直接交给平台适配器，发送前的
        on_decorating_result 拿到的是已经发完的完整文本，改动不会生效，
        所以只能在 send_streaming 这一层把生成器包一层。
        """
        self, event = _resolve_self(self, event)
        if self is None or event is None:
            _warn_unbound_once()
            return
        try:
            if not self._alive():
                _restore_patches()
                return
            if not self._enabled_for(event):
                # 配置关掉了 / 会话关了：别装补丁，已经装过的也撤掉
                _restore_patches(owner=self)
                return
            self._install_stream_hooks(type(event))
        except Exception:
            logger.exception("[火星文] 安装流式转换钩子失败。")

    # ------------------------------------------------------------------ 流式补丁
    def _install_stream_hooks(self, event_cls: type) -> None:
        """装 send_streaming 补丁；插件被重载时换成新实例的包装。

        只包事件类实际解析到的那一个实现（MRO 里第一个定义它的类），
        不往基类上层层叠，回滚时一条记录对一处属性。
        """
        _restore_patches(only_dead=True)
        for cls in getattr(event_cls, "__mro__", (event_cls,)):
            current = cls.__dict__.get("send_streaming")
            if current is None:
                continue
            if getattr(current, "_huoxing_owner", None) is self:
                return
            # 旧版本/上一次安装留下的包装要剥到底，否则重载后仍指向旧实例
            original = _peel_wrappers(current)
            setattr(cls, "send_streaming", self._make_send_streaming(original))
            _record_patch(cls, "send_streaming", original, self)
            return

    def _make_send_streaming(self, original):
        plugin = self

        async def send_streaming(self, generator, *args, **kwargs):
            return await original(
                self,
                plugin._convert_stream(self, generator),
                *args,
                **kwargs,
            )

        send_streaming._huoxing_owner = self
        send_streaming._huoxing_patched = True
        send_streaming.__wrapped__ = original
        return send_streaming

    async def _convert_stream(self, event: AstrMessageEvent, generator):
        """逐片转换流式输出；不转换时原样透传。"""
        active = False
        try:
            active = (
                self.is_active(event)
                and bool(self._cfg("only_llm", True))
                and self._roll()
            )
        except Exception:
            logger.exception("[火星文] 判定流式转换失败，已原样输出。")

        if not active:
            if not self._alive():
                _restore_patches()
            async for chunk in generator:
                yield chunk
            return

        event.set_extra("_huoxing_stream", True)
        async for chunk in generator:
            if not self._alive():
                # 输出到一半插件被停用/卸载：剩下的原样放行，顺手摘掉补丁
                _restore_patches()
                yield chunk
                continue
            try:
                if getattr(chunk, "type", None) not in {"reasoning", "audio_chunk"}:
                    # 流式逐片转换时不开首尾装饰，否则每个分片都会被加一遍符号
                    self._convert_chain_inplace(
                        getattr(chunk, "chain", None) or [],
                        decorate=False,
                    )
            except Exception:
                logger.exception("[火星文] 流式分片转换失败，已原样输出。")
            yield chunk

    # ------------------------------------------------------------------ 指令
    @filter.command("火星文", alias={"hxw", "火文"})
    async def huoxing_switch(self, event: AstrMessageEvent = None, action: str = "") -> None:
        """火星文开关：/火星文 [开|关|状态]"""
        self, event, action = _unpack_unbound(self, event, action)
        if self is None or event is None:
            _warn_unbound_once()
            if event is not None:
                yield event.plain_result(
                    "火星文插件没有正确加载，请在 WebUI 里重新启用本插件。",
                )
            return
        event.set_extra("_huoxing_skip", True)
        key = self._session_key(event)
        word = (action or "").strip().lower()

        if word in ON_WORDS:
            self._session_state[key] = True
        elif word in OFF_WORDS:
            self._session_state[key] = False
        elif not word or word in {"切换", "toggle"}:
            self._session_state[key] = not self.is_active(event)
        # 其它词（含「状态」）只回报当前状态，不改动开关

        self._save_state()
        active = self.is_active(event)
        mode = MODE_LABELS.get(str(self._cfg("mode", "huoxing")), "火星文")
        state_text = "已开启" if active else "已关闭"
        yield event.plain_result(
            f"火星文转换{state_text}（当前模式：{mode}）。\n"
            f"发送 /火星文 开 或 /火星文 关 可以随时切换。",
        )

    @filter.command("火星文预览", alias={"hxwy"})
    async def huoxing_preview(self, event: AstrMessageEvent = None) -> None:
        """预览三种模式的效果：/火星文预览 要转换的文本"""
        self, event = _resolve_self(self, event)
        if self is None or event is None:
            _warn_unbound_once()
            if event is not None:
                yield event.plain_result(
                    "火星文插件没有正确加载，请在 WebUI 里重新启用本插件。",
                )
            return
        event.set_extra("_huoxing_skip", True)
        raw = (event.get_message_str() or "").strip()
        text = raw
        for name in ("火星文预览", "hxwy"):
            idx = raw.find(name)
            if idx != -1:
                text = raw[idx + len(name) :].strip()
                break
        if not text:
            yield event.plain_result("用法：/火星文预览 要转换的文本")
            return
        lines = [f"· {MODE_LABELS[mode]}：{to_martian(text, mode=mode)}" for mode in MODES]
        yield event.plain_result("\n".join(lines))

    async def terminate(self) -> None:
        """停用 / 卸载 / 重载时收尾：撤掉类补丁、解绑 handler、存会话开关。"""
        _restore_patches(owner=self)
        self._unbind_handlers()
        self._save_state()
