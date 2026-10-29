"""火星文转换插件。

把模型最终输出的文本整段转成火星文（或繁体字 / 混排）再发送。
码表与 huoxingwen.qianwanku.com 一致，另外支持代码块、链接、@ 的原样保留，
以及可选的火星文装饰符号。
"""

from __future__ import annotations

import json
import random
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

PLUGIN_NAME = "astrbot_plugin_huoxingwen"
STATE_FILE = "session_state.json"

ON_WORDS = {"开", "开启", "on", "1", "true", "启用"}
OFF_WORDS = {"关", "关闭", "off", "0", "false", "停用"}


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
        if self._state_path is None:
            return
        try:
            self._state_path.write_text(
                json.dumps(self._session_state, ensure_ascii=False, indent=2),
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

    def is_active(self, event: AstrMessageEvent) -> bool:
        """当前会话是否需要转换。"""
        if not bool(self._cfg("enabled", True)):
            return False
        flag = self._session_state.get(self._session_key(event))
        if flag is not None:
            return flag
        return self._scope_ok(event)

    # ------------------------------------------------------------------ 转换
    def _convert(self, text: str) -> str:
        return to_martian(
            text,
            mode=str(self._cfg("mode", "huoxing")),
            protect_code=bool(self._cfg("protect_code", True)),
            protect_url=bool(self._cfg("protect_url", True)),
            protect_at=bool(self._cfg("protect_at", True)),
            decorate=bool(self._cfg("decorate", False)),
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

    def _convert_chain_inplace(self, chain) -> int:
        converted = 0
        for comp in chain:
            if not isinstance(comp, Plain):
                continue
            text = getattr(comp, "text", "") or ""
            if not text.strip():
                continue
            new_text = self._convert(text)
            if new_text != text:
                comp.text = new_text
                converted += 1
        return converted

    @filter.on_decorating_result(priority=100)
    async def on_decorating_result(self, event: AstrMessageEvent) -> None:
        """发送前把结果链里的纯文本段换成火星文。"""
        try:
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
    async def install_stream_hook(self, event: AstrMessageEvent, request=None) -> None:
        """真正调用模型前，给当前平台的事件类装好流式转换钩子。

        流式输出时 AstrBot 会把分片直接交给平台适配器，发送前的
        on_decorating_result 拿到的是已经发完的完整文本，改动不会生效，
        所以只能在 send_streaming 这一层把生成器包一层。
        """
        try:
            self._install_stream_hooks(type(event))
        except Exception:
            logger.exception("[火星文] 安装流式转换钩子失败。")

    # ------------------------------------------------------------------ 流式补丁
    def _install_stream_hooks(self, event_cls: type) -> None:
        """装 send_streaming 补丁；插件被重载时换成新实例的包装。"""
        for cls in getattr(event_cls, "__mro__", (event_cls,)):
            current = cls.__dict__.get("send_streaming")
            if current is None:
                continue
            if getattr(current, "_huoxing_owner", None) is self:
                continue
            # 上一次安装留下的包装要剥掉，否则重载后仍指向旧实例（配置不会更新）
            original = getattr(current, "__wrapped__", current)
            setattr(cls, "send_streaming", self._make_send_streaming(original))

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
            async for chunk in generator:
                yield chunk
            return

        event.set_extra("_huoxing_stream", True)
        async for chunk in generator:
            try:
                if getattr(chunk, "type", None) not in {"reasoning", "audio_chunk"}:
                    self._convert_chain_inplace(getattr(chunk, "chain", None) or [])
            except Exception:
                logger.exception("[火星文] 流式分片转换失败，已原样输出。")
            yield chunk

    # ------------------------------------------------------------------ 指令
    @filter.command("火星文", alias={"hxw", "火文"})
    async def huoxing_switch(self, event: AstrMessageEvent, action: str = "") -> None:
        """火星文开关：/火星文 [开|关|状态]"""
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
    async def huoxing_preview(self, event: AstrMessageEvent) -> None:
        """预览三种模式的效果：/火星文预览 要转换的文本"""
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
        self._save_state()
