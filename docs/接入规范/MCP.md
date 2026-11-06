# 祀音 MCP 接入规范

版本：1.0.0；核对日期：2026-11-06。实现：app/services/mcp/mcp_server.py。

## 1. 用途与传输

MCP 提供本机工具调用：状态、音色、合成到 WAV、调参、参考音频、切换音色和预热。自身不加载模型，依赖已启动的本机网关/引擎。

| 项目 | 当前实现 |
|---|---|
| 传输 | stdio，stdin/stdout 逐行 UTF-8 JSON |
| 消息 | JSON-RPC 2.0，每条 JSON 后一个换行 |
| protocolVersion | 2024-11-05 |
| serverInfo | name: gsv-tts；version: 1.0.0 |
| 能力 | tools；listChanged=false |
| 方法 | initialize、notifications/initialized、ping、tools/list、tools/call |
| 日志 | stderr，stdout 仅协议 |
| 不提供 | HTTP/SSE/Streamable HTTP MCP、资源订阅、音频二进制推送 |

这是本机 stdio MCP；将 9881 转发到公网不会产生远程 MCP 端点。其他设备开发通常直接使用 HTTP API；如需远程 MCP，需要另外实现经过鉴权的适配层。

## 2. 客户端配置

先双击项目根目录的祀音.exe 等待服务就绪，再由 MCP 客户端启动以下命令：

~~~json
{
  "mcpServers": {
    "gsv-tts": {
      "command": "<PROJECT_ROOT>\\app\\python\\python.exe",
      "args": ["<PROJECT_ROOT>\\app\\services\\mcp\\mcp_server.py"]
    }
  }
}
~~~

路径按安装位置替换。使用 python.exe 保留 stdin/stdout 管道，不要改用桌面 EXE 或 pythonw.exe。当前 MCP 从自身相邻的 app/services/config.json 读取 gateway.token，不需要在客户端配置中粘贴 Key，也没有可配置的远程 baseURL。通过本机进程权限使用这些工具，不依赖 HTTP API Key 来限制 MCP 本地工具权限。

## 3. 返回和错误

tools/call 成功结果：

~~~json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"ok\":true}"}]}}
~~~

业务对象是 result.content 中 type=text 项的 text 所含 JSON 字符串，需要再做一次 JSON 解析。不要把 result.ok 当成业务状态。

工具参数或运行错误通常以 result.isError=true 表示，text 为包含 error 字段的 JSON。未知工具返回 JSON-RPC error.code=-32602；未知方法 -32601；非法 JSON -32700。客户端同时检查顶层 error、result.isError 和业务对象中的 ok（存在时）。

各工具有的会写文件或修改全局配置。客户端不能只依赖工具 schema 做授权；当前服务器也未对所有 schema 字段实施统一 JSON Schema 强校验，调用方应发送已声明的参数。

## 4. 七个工具

所有工具的精确 inputSchema 见同目录 mcp-tools.json，或运行时 tools/list。

### tts_status

参数：空对象 {}。

返回 ok、engine、gateway、engine_http、gateway_http、voice、default_voice、queue、reloading、sidecar、gpu、active_requests、stats 等。网络故障时可有分项 error；字段可能缺失。ok 是引擎和网关均就绪的综合状态。

### tts_list_voices

参数：{}。

返回 current、default、tts_defaults、audio、voices。音色项含 name、语言、speed_factor、sample_steps、ref_audio_path、prompt_text、has_reference。文件路径是运行 MCP 的电脑上的路径。

### tts_speak

| 参数 | 类型 | 要求 |
|---|---|---|
| text | string | 必填；非空，规范流式网关上限 2000 字符 |
| voice | string | 可选；默认 default_voice，当前 si |
| speed_factor | number | 可选；默认音色配置，当前 0.88；网关有效范围 0.1～4.0 |
| out_path | string | 可选；运行 MCP 的电脑上的目标 WAV 路径 |

返回 ok、path、voice、speed_factor、sample_rate、duration_s、first_byte_ms、total_ms、bytes。

固定保存 24000Hz / 单声道 / 16 位 WAV。bytes 是 PCM 数据字节数，不含 WAV 头；path 是本地文件路径，不是可远程下载的 URL。工具会把音频收集到内存后写文件，实时低延迟播放应走 HTTP 流式 API。

out_path 省略时保存到项目 app/out/mcp_YYYYMMDD_HHMMSS.wav；运行时按脚本位置解析，不依赖 F:。当前 tools/list 的 out_path 描述仍保留旧 F: 示例，这属于描述遗留；以这里的实际解析行为为准。

自定义 out_path 的父目录须已存在；工具不会为自定义路径自动建目录。默认文件名精确到秒，同秒重复调用可能覆盖已有同名输出，开发集成宜传入含 UUID 的文件路径。该工具不自动把输出登记到桌面作品库，也没有独立的 48kHz/MP3 输出参数。

~~~json
{"text":"你好，这是其他应用调用祀音的示例。","voice":"si","speed_factor":0.88,"out_path":"D:\\audio-output\\sample-unique.wav"}
~~~

### tts_set_params

至少传入一项：

| 参数 | 类型 | 范围与作用 |
|---|---|---|
| speed_factor | number | 0.1～4.0；改全局默认及所有已配置音色 |
| sample_steps | integer | 1～48；改全局默认及所有已配置音色；正常建议保持 4 |
| default_voice | string | 须是已配置音色 |
| segment_pause_ms | integer | 0～5000 |

原子保存配置，返回 ok、changed、effective。并非只修改下一次调用，也不是仅修改某个 voice。已运行网关保留启动时读取的配置，因此改后需重启网关；工具不自动重启。MCP 后续读取配置的调用可能先看到新值。

~~~json
{"speed_factor":0.88,"sample_steps":4,"default_voice":"si","segment_pause_ms":200}
~~~

### tts_set_reference

三个参数都必填：voice(string)、ref_audio_path(string)、prompt_text(string)。

保存指定音色的参考音频路径和对应文本，返回 ok、voice、effective、ref_exists。参考音频用于音色/语气条件，文本应和样本实际语音一致。

路径是服务电脑上的文件。ref_exists=false 仍可能已经保存路径，不代表操作回滚；调用方应先检查文件，再处理返回。重启网关后读取新参考配置，当前已排队/正在运行的合成不承诺立即变化。

~~~json
{"voice":"si","ref_audio_path":"D:\\reference\\sample.wav","prompt_text":"样本中实际说出的文字。"}
~~~

### tts_switch_voice

name(string) 必填，表示引擎识别的完整音色/权重名称，例如 si。

调用底层引擎 /set_gpt_weights，受合成共享互斥保护，可能等待当前任务完成。返回 ok、requested、elapsed_s、engine。不等同于仅设置默认音色，也不保证改写 default_voice。切换耗时依模型与硬件而变；客户端应允许足够长的超时。不要在每段文本前重复切换。

### tts_warmup

可选 text(string)，省略时用 audio.warmup_text 或内部默认短句。

实际执行一次合成并丢弃音频；返回 ok、text、elapsed_s、audio_seconds、wav_bytes。会占用合成资源，不是无开销的状态查询。

## 5. JSON-RPC 握手与调用示例

每个代码行是一条实际发送的 JSON，不加 Content-Length 头；notifications/initialized 不返回响应。

~~~json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"your-app","version":"1.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"tts_status","arguments":{}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"tts_speak","arguments":{"text":"你好。","voice":"si"}}}
~~~

请求 id 用于响应匹配。当前服务逐行、顺序处理请求，长时间合成时同一连接的后续请求需要等待。没有 MCP notifications/cancelled 的实际中断实现；客户端终止进程也不保证底层正在执行的 GPU 推理马上结束。

## 6. 实现边界与接入建议

- 当前是固定 protocolVersion 的轻量实现，不宣称支持所有 MCP 新版本能力；客户端须允许与此版本协商。
- 实时播放和远程设备用 HTTP API；本机参数管理和合成到文件可用 stdio MCP。
- HTTP、MCP 与桌面任务共享模型互斥，不为每个客户端启动一套引擎。
- 合成文件由 MCP 自己保存；工作台导出/搜索/队列属于另外的本地接口，七个 MCP 工具没有自动提供全部桌面功能。
- 修改默认参数或参考音频后，先重启网关，再用 tts_status 检查就绪状态。

本轮从实际 stdio 进程核对 initialize、tools/list、tts_status；七项名称与参数定义来自运行结果，未为了编写文档修改用户参数或切换模型。

