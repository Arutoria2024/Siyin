# 祀音 HTTP API 接入规范

版本：1.1.0；核对日期：2026-11-06（英文与离线后处理更新）。实现：app/services/gateway/gateway.py、app/desktop/lan_access.py。

## 1. 服务地址与职责

| 服务 | 本机地址 | 外部应用用途 |
|---|---|---|
| 语音网关 | http://127.0.0.1:9881 | 对外合成 API |
| 可选局域网入口 | http://<LAN_IP>:9890 | 页面自动显示实际网卡 IP；端口可在设置页修改 |
| 本机工作台 | http://127.0.0.1:9888 | 默认回环端口；局域网入口另外提供受保护界面 |
| 引擎、文本服务 | 127.0.0.1:9880 / :9882 | 内部服务，不对外转发 |

先启动祀音，等服务就绪，并在“接入与设置 → 网络访问”打开局域网开关。其他设备可通过局域网入口打开浏览器工作台（API Key 登录），或调用同一地址下的 API。服务电脑关机、休眠、退出提供入口的监控服务或关闭局域网开关时，远程访问不可用。

本机网关固定 127.0.0.1:9881；局域网入口监听 0.0.0.0:9890（端口可配置），转发既有 API 并提供受保护的工作台。新安装局域网默认关闭，本机保持开启。页面显示本机网卡 IP，Windows 防火墙操作为当前安装的 Python 进程创建专属 TCP/LocalSubnet 规则，需要管理员授权。关闭开关停止监听，规则保留供下次开启；可在设置页重新配置规则。仍不包含路由器自动映射或内置公网隧道。

## 2. API Key

配置位置：项目 app/services/config.json 的 gateway.token。已有安装使用本机现有值；新安装由 bootstrap 生成独立值。该配置被网关启动时读取，修改后要重启网关。

推荐请求头：

~~~http
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json
~~~

兼容 X-Auth-Token 请求头及 token 查询参数，优先使用 Authorization，避免 URL 携带密钥。当前是一把共享 Key，不支持多用户独立 Key、到期时间、配额或在线吊销。更换 Key 后所有调用方要同步更新。

本机 9881 保留所有 POST 校验 Key、健康/音色 GET 不要求 Key 的兼容行为。局域网入口的 API 包括健康和音色 GET 均校验 Key，OPTIONS 为预检保留免鉴权。浏览器工作台 /login 使用同一 Key 登录，以 HttpOnly/SameSite 会话保护页面和作品；修改网络设置与读取 Key 仅在本机可用。不要把网页 Cookie 当作 API 请求的 Bearer Key。

应直接配置 gateway.token；当前版本不要依赖 GSV_TTS_TOKEN 环境变量作为唯一网关鉴权来源，启动日志的环境变量回退与实际请求校验尚未统一。

## 3. 端点

下表是语音网关契约。局域网入口转发这些 /v1/...、/health 和 /voices 路径；其根路径 / 用于网页工作台登录，不返回原网关的服务信息。工作台登录 POST /login 使用表单字段 key，成功后设置八小时 HttpOnly/SameSite Cookie；第三方语音应用通常直接使用 Bearer API，不需要网页登录。

| 方法 | 路径 | 输出 |
|---|---|---|
| GET | / 或 /v1/health、/health | / 返回服务信息；health 返回就绪与运行指标 |
| GET | /v1/voices 或 /voices | 可用音色 |
| POST | /v1/text-to-speech/{voice_id}/stream | 首选：流式 PCM，或流式 WAV |
| POST | /v1/tts | 兼容：完整 WAV 文件 |
| POST | /v1/tts/stream | 兼容：旧版流式 WAV/PCM |
| OPTIONS | 路径 | CORS 预检 |

没有 /tts 或 OpenAI /v1/audio/speech 兼容端点。局域网工作台可使用任务和导出，但其 /api/workbench/... 属于工作台内部会话接口，不作为第三方稳定公共契约；桌面支持的 MP3、FLAC、AAC 等没有自动成为语音网关输出格式。

## 4. 健康和音色

~~~http
GET /v1/health
~~~

主要字段示例（值仅示意）：

~~~json
{
  "ok": true,
  "model": "si",
  "voice": "si",
  "sample_rate": 24000,
  "channels": 1,
  "format": "pcm_s16le",
  "sample_steps": 4,
  "gpu": null,
  "engine": {"ok": true},
  "default_voice": "si",
  "voices": ["si"],
  "stats": {},
  "active_requests": {},
  "limits": {"concurrent_per_ip": 2},
  "time": 0
}
~~~

HTTP 200 仅代表网关响应；以 ok 判断模型是否就绪。gpu 可能为 null。stats 等字段可增加，客户端应容忍未知字段。

~~~http
GET /v1/voices
~~~

返回 current、default、voices 数组；每项包含 name、text_lang、prompt_lang、sample_steps、has_reference。音色 ID 以此结果为准，不把用户界面显示名称用作 ID。

## 5. 首选流式合成

~~~http
POST /v1/text-to-speech/si/stream?output_format=pcm&sample_rate=24000
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json

{"text":"你好，欢迎使用祀音。","speed":0.88}
~~~

请求参数可放查询字符串或 JSON，JSON 同名字段优先。

| 参数 | 类型 | 要求/默认值 |
|---|---|---|
| voice_id | 路径字符串 | 必填；例如 si；须在配置音色中 |
| text | 字符串 | 必填，去首尾空白后 1～2000 字符；Python 字符计数 |
| input | 字符串 | text 的兼容别名；优先传 text |
| output_format | 字符串 | pcm（默认）、pcm_s16le、s16le、wav |
| sample_rate | 整数 | 24000（默认）或 48000 |
| speed | 数值 | 0.1～4.0；缺省取音色配置，当前 si 为 0.88 |
| speed_factor | 数值 | speed 的兼容别名 |
| sample_steps | 整数 | 建议省略；沿用配置 4。接口未严格统一校验所有边界，不应传未经验证的高值 |
| model_id | 任意 | 当前不参与模型选择；未知参数通常被忽略 |

选择音色会影响合成后端；不要并发交替不同模型。长文调用方应按句段拆分为不超过 2000 字符的顺序请求；网关不返回工作台任务 ID，也不自动保存分段恢复记录。

成功响应：

~~~http
HTTP/1.1 200 OK
Content-Type: audio/pcm
Transfer-Encoding: chunked
Cache-Control: no-store
X-Accel-Buffering: no
X-Sample-Rate: 24000
X-Channels: 1
X-Format: pcm_s16le
X-Voice: si
~~~

PCM：无文件头、16 位有符号小端、单声道。24kHz 每秒 48000 字节；48kHz 每秒 96000 字节。时长 = PCM 字节数 / (采样率 × 2)。

网络分块不等于样本边界。客户端必须保留跨包的奇数字节，与下一块拼接后再解析 Int16；播放浮点样本通常为 int16 / 32768。建议累计约 500ms 音频再起播，采用有界缓冲或边接收边落盘。HTTP 客户端负责解码 chunked 传输，音频中不要保留 HTTP 分块长度行。

output_format=wav 时 Content-Type 为 audio/wav，前置用于流式播放的 WAV 头，长度为流式占位值；需要准确文件长度和广泛播放器兼容时使用 /v1/tts 或重新封装 PCM。

收到 200 后仍可能中途失败；检查读取异常、空音频、末尾奇数字节和终止状态。开始传音频后错误通过断开/截断传输表示，不会在 PCM 中插入 JSON。若代理掩盖了截断，客户端无法仅凭已播放声音保证文本全部完成。

浏览器跨域 fetch 可读取音频，但当前未发送 Access-Control-Expose-Headers，自定义 X-* 头在跨域 JavaScript 中可能不可读。已知采样率可由请求配置确定，或通过自己服务端中转；不要假设跨域能直接读取这些头。

## 6. 完整 WAV 和旧接口

~~~http
POST /v1/tts
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json

{"text":"你好。","voice":"si","speed":0.88,"sample_rate":24000}
~~~

等全部合成后返回 audio/wav、准确 Content-Length 和 X-Audio-Seconds。参数还兼容 input、speed_factor、sr；此路径不采用 output_format。为一致性，建议调用方同样限制单次不超过 2000 字符。

旧流式 /v1/tts/stream 使用 format=wav（默认）、pcm 或 l16，而不是 output_format。即使旧 PCM 路径标注 audio/L16，实际字节仍为小端 s16le，不按网络大端解码。新应用优先使用第 5 节契约。

## 7. 错误、排队和取消

错误 JSON 一般形如：

~~~json
{"error":"invalid or missing token","code":401}
~~~

| 情况 | 行为 |
|---|---|
| 未带/错误 API Key | HTTP 401 |
| 缺文本、超过规范流式长度、非法采样率/语速/格式 | HTTP 400 |
| 未知路径或规范端点中的未知音色 | HTTP 404 |
| 同 IP 超过并发上限（当前 2） | HTTP 429，并有 Retry-After: 2 |
| 内部故障 | 可能 500，或开始音频后截断/断流 |

单 GPU 共享跨进程合成互斥，外部 API、MCP 与工作台串行占用。并发连接上限不代表同时有多份模型推理。当前没有网关任务 ID、幂等键、结果缓存、显式 HTTP 取消端点；断开连接不保证正在执行的底层推理立即退出。

429 按 Retry-After 退避；401/400 不盲目重试。断流重试可能重新合成整句、重复计时和播放，客户端应由业务决定是否重试。连接和读取超时需覆盖模型生成及排队；代理超时建议按最长文本实际测试设置，不能套用几秒钟的普通接口超时。

## 8. Python 示例：保存 WAV（标准库）

运行前由调用方环境设置 SIYIN_API_KEY；这是示例客户端的环境变量，不是网关配置变量。

~~~python
import json, os, urllib.request, urllib.error

base = os.environ.get("SIYIN_BASE_URL", "http://<LAN_IP>:9890")
key = os.environ["SIYIN_API_KEY"]
req = urllib.request.Request(
    base.rstrip("/") + "/v1/tts",
    data=json.dumps({"text": "你好，接口连接成功。", "voice": "si"},
                    ensure_ascii=False).encode("utf-8"),
    headers={"Authorization": "Bearer " + key,
             "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=300) as response:
        with open("祀音示例.wav", "wb") as output:
            while chunk := response.read(65536):
                output.write(chunk)
except urllib.error.HTTPError as error:
    raise RuntimeError(f"HTTP {error.code}: "
                       + error.read().decode("utf-8", "replace")) from error
~~~

## 9. JavaScript 示例：逐块接收 PCM

Node 18+ / 支持 fetch 流的环境可复用以下逻辑。onSamples 是调用方提供的有界队列/音频播放接收器。

~~~javascript
async function synthesizePcm({base, key, text, onSamples, signal}) {
  const response = await fetch(
    base.replace(/\/$/, "") +
      "/v1/text-to-speech/si/stream?output_format=pcm&sample_rate=24000",
    {
      method: "POST",
      headers: {"Authorization": "Bearer " + key,
                "Content-Type": "application/json"},
      body: JSON.stringify({text}),
      signal,
    }
  );
  if (!response.ok) {
    throw new Error("HTTP " + response.status + ": " + await response.text());
  }
  if (!response.body) throw new Error("缺少音频流");
  const reader = response.body.getReader();
  let pending = new Uint8Array(0), total = 0, completed = false;
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      const bytes = new Uint8Array(pending.length + value.length);
      bytes.set(pending);
      bytes.set(value, pending.length);
      const size = bytes.length - bytes.length % 2;
      const view = new DataView(bytes.buffer, bytes.byteOffset, size);
      const samples = new Float32Array(size / 2);
      for (let i = 0; i < samples.length; i++) {
        samples[i] = view.getInt16(i * 2, true) / 32768;
      }
      pending = bytes.slice(size);
      total += size;
      if (samples.length) await onSamples(samples, 24000);
    }
    if (!total || pending.length) throw new Error("空流或不完整 PCM 样本");
    completed = true;
  } finally {
    if (!completed) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  return {sampleRate: 24000, channels: 1, audioSeconds: total / 48000};
}
~~~

该函数演示接收和样本解析，不包含完整播放器、AudioWorklet 或自动格式转换。

## 10. 服务器跳接到公网

拓扑：

公网设备 → HTTPS 域名/服务器反向代理 → 私有隧道 → 服务电脑可选局域网入口（默认 9890，支持页面及 API）。仅需要语音 API 的部署也可以在严格受保护的隧道内连接 127.0.0.1:9881。

当前程序没有创建隧道、配置服务器、域名证书或路由器自动端口转发；这些需在后续部署时单独配置。已有服务器时可以让服务电脑主动建立私有隧道，终点选已启用的入口。当前局域网页面 Cookie 无 Secure 标记以支持局域网 HTTP；公网必须使用 HTTPS 入口并按实际反代方式验证 Cookie 与 Origin。

代理必须保留 Authorization；对流式响应关闭缓冲/缓存/压缩聚合，保持持续分块传输；设置覆盖排队/生成的读取超时。服务器 HTTPS 负责加密公网传输，内侧可通过受保护的隧道访问本机 HTTP。限制服务器转发端口的访问范围，避免绕过 HTTPS 入口。

不直接转发 9880、9882 或本机管理端口。局域网入口对 API GET/POST 均要求 Key；若选本机 9881 作为隧道终点，其健康/音色 GET 仍需在公网入口补充鉴权。代理的限流应以实际可信客户端地址为准；当前网关会读取 X-Forwarded-For，局域网转发会覆盖为直接连接方 IP，不能把它单独当作公网抗滥用保障。

未实施公网端到端验证。不要在客户端中把 0.0.0.0 作为访问地址。

## 11. 1.1.0：英文与成品后处理

所有合成请求新增可选 `text_lang`：`en` 英文，`auto` 中英混合；省略时沿用音色语言（si 为 zh）。还接受 `zh/auto_yue/ja/ko/yue/all_zh/all_ja/all_ko/all_yue`，具体音色跨语言能力需验证；本轮验证中文、英文、中英混合。不改变中文参考音频的 `prompt_lang`。

流式接口维持原声 PCM，`postprocess` 只可省略或为 false；传 true 返回 400。不能等流已发送后再补处理，也不改变 PCM 包契约。

完整 WAV 接口 `POST /v1/tts` 新增可选布尔 `postprocess`，默认读取配置（未配置默认开启）。后处理为呼吸抑制、EQ、动态与响度；响应 `X-Postprocess: finished/raw`。离线处理结束后返回，耗时包含实际处理时间。缺少 FFmpeg 或处理失败返回 500，不静默当成已处理。关闭时保持原始 PCM：

```json
{"text":"Hello, welcome to Siyin.","voice":"si","text_lang":"en","postprocess":true}
```

此接口只返回 WAV，不自动为调用方存档原声。需要原声和交付版本一同保存，可使用工作台任务或 MCP `tts_speak`。母版与处理参数说明见 [英文与后处理升级](../英文与后处理升级.md)。网关常驻配置变更仍需重启；实时流不会因此增加整轨等待时间。

