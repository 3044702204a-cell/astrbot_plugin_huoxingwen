"""离线自测：python tests/test_convert.py（在插件目录下运行）"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from huoxing import MODES, to_martian  # noqa: E402


def main() -> None:
    sample = "今天天气不错，我们一起去吃饭吧！详情看 https://example.com/a?b=1 或者 `pip install foo`"
    for mode in MODES:
        print(mode, "->", to_martian(sample, mode=mode))
    print("decorated ->", to_martian("我爱你", decorate=True))
    print("code keep ->", to_martian("```python\nprint('你好')\n```"))

    import main as plugin_main  # noqa: E402

    class FakeResult:
        def __init__(self, text: str) -> None:
            self.chain = [plugin_main.Plain(text)]
            self.result_content_type = None
            self.async_stream = None

        def is_model_result(self) -> bool:
            return True

    class FakeEvent:
        unified_msg_origin = "webchat:FriendMessage:1"
        message_str = "/火星文预览 你好呀"

        def __init__(self, text: str) -> None:
            self._result = FakeResult(text)

        def get_result(self):
            return self._result

        def get_message_type(self):
            return plugin_main.MessageType.FRIEND_MESSAGE

        def set_extra(self, key, value):
            pass

        def get_extra(self, key=None, default=None):
            return default

    plugin = object.__new__(plugin_main.HuoxingwenPlugin)
    plugin.config = {"enabled": True, "mode": "huoxing", "probability": 100}
    plugin._rng = __import__("random").Random(0)
    plugin._state_path = None
    plugin._session_state = {}

    event = FakeEvent("今天天气不错，我们一起去吃饭吧")
    asyncio.run(plugin.on_decorating_result(event))
    print("hook ->", event.get_result().chain[0].text)


if __name__ == "__main__":
    main()
