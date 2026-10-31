# 火星文转换

[![version](https://img.shields.io/github/v/release/3044702204a-cell/astrbot_plugin_huoxingwen?label=version&color=informational)](https://github.com/3044702204a-cell/astrbot_plugin_huoxingwen/releases)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.x-2b6cb0)](https://github.com/AstrBotDevs/AstrBot)
[![license](https://img.shields.io/github/license/3044702204a-cell/astrbot_plugin_huoxingwen)](LICENSE)

把 AstrBot 里模型回复整段转成火星文再发出去，效果类似
<http://huoxingwen.qianwanku.com/>。

版本 `1.3.1` ｜ 兼容 AstrBot `4.x`（`>=4.0,<5`） ｜ 流式 / 非流式都可以转 ｜ 平台无关

## 安装

- 插件市场搜「火星文转换」直接安装；
- 或者手动：把仓库克隆到 `data/plugins/astrbot_plugin_huoxingwen`，重启 AstrBot。

```bash
git clone https://github.com/3044702204a-cell/astrbot_plugin_huoxingwen.git data/plugins/astrbot_plugin_huoxingwen
```

没有额外依赖，装完在配置里开关一下就生效。

## 效果

| 原文 | 火星文 |
| --- | --- |
| 今天天气不错，我们一起去吃饭吧 | 妗兲兲氣芣措，莪們①起厾阣粄妑 |
| 我爱你 | 莪嬡沵 |
| 你是笨蛋吗 | 沵湜笨蛋嬤 |

## 原理

- 码表直接取自 huoxingwen.qianwanku.com 的 `huoxing.js`：三张等长码表
  （简体 / 繁体 / 火星文）按索引一一对应，存放在 `huoxing_tables.py`，转换是
  纯字符映射，不需要联网和分词。
- 非流式输出：在 `on_decorating_result`（发送消息前）钩子里遍历结果链，只改写
  `Plain` 文本段，图片、语音、Reply、At 等组件原样保留。
- 流式输出：AstrBot 会把分片直接交给平台适配器，发送前钩子拿到的是已经发完的
  整段文本，改它没用。所以本插件在 `on_llm_request` 时给当前平台的事件类装一个
  `send_streaming` 包装，逐片转换后再交给平台；同一个会话只装一次，转换过的消息
  会打标记，避免和发送前钩子重复转换。
- 这种类属性补丁不在 handler 注册表里，插件不主动撤就会活到进程重启，于是插件
  自己拿一份台账（类 / 属性 / 原函数 / 装的实例）：`terminate()` 精确回滚，
  每次转换前还会重新确认这份实例是否仍是 `star_map` 里那个 `star_cls`，
  停用、卸载、热重载、手动删目录之后都不会再有残留转换。
- 分片中 `reasoning`（思维链）与 `audio_chunk`（语音流）不参与转换。
- 流式下只做字符映射：`decorate`（首尾装饰符号）在流式输出时会跳过，否则每个分片都会被套一遍符号；想要装饰就把流式关掉。
- 代码块、行内代码、链接、`@某人`、CQ 码会被屏蔽后原样拼回，避免把代码和
  链接转成乱码。

## 兼容性

- AstrBot `>=4.0,<5`：只用 `astrbot.api` 的公开接口（`Star`、`filter`、
  `AstrMessageEvent`）干活；另外会尝试读一次 `astrbot.core.star` 里的插件注册表，
  仅用于「插件以停用态被加载、handler 没绑到实例」时兜底，读不到就降级为只告警一次，
  不影响转换。
- 停用 / 卸载 / 热重载：插件自己回滚打在平台事件类上的 `send_streaming` 包装
  （详见「原理」最后一节），不依赖框架版本有没有统一回滚；旧版本残留的包装在下次
  安装补丁时会被剥掉。
- 平台无关：任何会走 `send_streaming` 的适配器（WebChat、Telegram、QQ 官方私聊等）
  都按同样方式转换；不支持流式的平台自动走非流式那条路。`metadata.yaml` 的
  `support_platforms` 列出了已验证的平台，没列的平台大概率也能用。
- 与其它改写结果的插件共存：只改动 `Plain` 文本段，遇到非模型输出默认不处理
  （`only_llm` 可调）。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/火星文` | 切换当前会话的开关（别名 `/hxw`、`/火文`） |
| `/火星文 开` / `/火星文 关` | 直接开启 / 关闭当前会话 |
| `/火星文 状态` | 查看当前状态 |
| `/火星文预览 文本` | 同时预览火星文、繁体、混排三种效果（别名 `/hxwy`） |

会话开关保存在 `data/plugin_data/astrbot_plugin_huoxingwen/session_state.json`。

## 配置

- `enabled`：总开关。
- `mode`：`huoxing` 火星文 / `traditional` 繁体字 / `mix` 随机混排。
- `only_llm`：只转换模型输出（默认开），其它插件的文本不受影响。
- `probability`：单条消息转换概率，100 表示全部转换。
- `decorate` + `decoration_chars`：首尾随机加 `ゞ ﹏ 灬` 之类的装饰符号。
- `protect_code` / `protect_url` / `protect_at`：保护代码、链接、@。
- `scope`：`both` / `group` / `private`。

## 自测

```bash
# 在插件目录下，用 AstrBot 自带的 Python
set PYTHONPATH=E:\AstrBot\backend\app
E:\AstrBot\backend\python\python.exe tests\test_convert.py
E:\AstrBot\backend\python\python.exe tests\test_stream_patch.py
E:\AstrBot\backend\python\python.exe tests\test_unbound_call.py
E:\AstrBot\backend\python\python.exe tests\test_unload_cleanup.py
```

## 许可

MIT，见 [LICENSE](LICENSE)。
