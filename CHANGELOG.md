# 更新日志

## 1.2.1

- 修复「handler 未绑定实例」导致的连环报错：插件以停用状态被加载时，AstrBot 不会实例化插件类，注册表里的 `on_decorating_result` / `on_llm_request` 保持未绑定函数，被调用时 `self` 收到的是 event，于是每条消息都会抛 `TypeError: missing 1 required positional argument: 'event'` 与 `AttributeError: 'AiocqhttpMessageEvent' object has no attribute '_install_stream_hooks'`。
  - 四个 handler 入口统一做调用形式归一化：检测到「未绑定调用」时从注册表取真实实例，取不到就只告警一次并静默跳过，不再每条消息刷异常。
  - 新增 `initialize()`：插件加载完成后主动把本插件所有 handler 绑到当前实例，顺手修掉旧版加载分支漏绑定、热重载后指向旧实例的情况。
  - 指令在实例缺失时回复一句「请在 WebUI 里重新启用本插件」，而不是静默失败。
- 新增 `tests/test_unbound_call.py`：覆盖未绑定调用、实例缺失、实例存在、正常绑定四种路径。

## 1.2.0

- 流式逐片转换时不再加首尾装饰符号（`decorate`）。之前每来一个分片都会套一遍 `ゞ ﹏ 灬`，整段读起来全是符号；现在流式下只做字符映射，装饰只在非流式整段发送时生效。
- `metadata.yaml` 补了 `tags` 与 `social_link`，市场里能显示标签。
- 测试补了「开启装饰时流式不加符号」用例。

## 1.1.1

- 修复插件重载后流式补丁仍指向旧实例的问题：重载时剥掉旧包装重新安装，面板里改配置（模式、概率、总开关）能立即对流式输出生效。
- `tests/test_stream_patch.py` 增加重载场景用例。

## 1.1.0

- 修复流式输出下火星文完全不生效的问题：改为在模型调用前给当前平台的事件类打 `send_streaming` 补丁，逐片转换后再交给适配器；关掉的会话原样透传。
- 去掉对流式结果 `result.async_stream` 的事后包裹（那个时机已经被消费，等于没生效）。
- 转换过的会话打事件标记，避免分片转换与发送前钩子重复转换。
- 跳过 `reasoning`、`audio_chunk` 类型的分片，不会把思维链和语音文本搅乱。
- 清理主文件里不再需要的 `MessageChain`、`ResultContentType` 导入，降低跨版本 ImportError 风险。

## 1.0.0

- 首次发布。
- 码表取自 huoxingwen.qianwanku.com 的 `huoxing.js`（简体 / 繁体 / 火星文三张等长码表）。
- 在发送前钩子 `on_decorating_result` 中改写 `Plain` 文本段，图片、语音、Reply、At 等组件不受影响。
- 流式输出场景改为包裹 `result.async_stream` 逐片转换，并用事件标记避免与发送前钩子重复转换。
- 代码块、行内代码、URL、`@某人`、CQ 码默认原样保留。
- 支持火星文 / 繁体字 / 随机混排三种模式，可选的装饰符号，单条消息转换概率。
- 指令：`/火星文`、`/火星文 开|关|状态`、`/火星文预览 文本`，会话开关持久化到插件数据目录。
