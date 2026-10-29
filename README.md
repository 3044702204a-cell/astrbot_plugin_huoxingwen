# 火星文转换

把 AstrBot 里模型最终输出的那段话整段转成火星文再发出去，效果类似
<http://huoxingwen.qianwanku.com/>。

## 安装

- 插件市场搜「火星文转换」直接安装；
- 或者手动：把仓库克隆到 `data/plugins/astrbot_plugin_huoxingwen`，重启 AstrBot。

```bash
git clone https://github.com/3044702204a-cell/astrbot_plugin_huoxingwen.git data/plugins/astrbot_plugin_huoxingwen
```

## 效果

| 原文 | 火星文 |
| --- | --- |
| 今天天气不错，我们一起去吃饭吧 | 妗兲兲氣芣措，莪們①起厾阣粄妑 |
| 我爱你 | 莪嬡沵 |
| 你是笨蛋吗 | 沵湜笨蛋嬤 |

## 原理

- 码表直接取自 huoxingwen.qianwanku.com 的 `huoxing.js`：三张等长码表
  （简体 / 繁体 / 火星文）按索引一一对应，存放在 `huoxing_tables.py`。
- 在 `on_decorating_result`（发送消息前）钩子里遍历结果链，只改写 `Plain`
  文本段，图片、语音、Reply、At 等组件原样保留。
- 开启流式输出时换成包裹 `result.async_stream` 的方式逐片转换，因为流式结果
  不会走发送前钩子。
- 代码块、行内代码、链接、`@某人`、CQ 码会被屏蔽后原样拼回，避免把代码和
  链接转成乱码。

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
```

## 许可

MIT，见 [LICENSE](LICENSE)。
