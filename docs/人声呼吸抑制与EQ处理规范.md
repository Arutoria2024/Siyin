# 人声呼吸抑制与 EQ 处理规范（祀音合成后处理）

> 版本 v1 · 2026-11-06
> 适用对象：祀音（gsv-tts）合成管线维护者
> 目的：解决合成音「呼吸音偏重、词间吸气明显」的问题，并给出可直接接入的后处理链、参数含义与验收方法。

---

## 1. 问题与判据

**现象**：合成音频在词与词之间能听到明显的吸气声，听感"喘"，长时间听会累。声音本身（音色、韵律）没有问题，是**气声成分**偏多。

**判据**（不是凭感觉，三条都要过）：

| 检查项 | 合格标准 |
|---|---|
| 人耳 A/B | 同一句处理前后对比，吸气声明显减弱，**字头、字尾、辅音不能被削薄** |
| ASR 回读 | 处理后的整轨转写与原文逐字一致（用硅基流动 SenseVoice 或同等级 ASR） |
| 电平 | 不追求整体 RMS 变化（见第 5 节，看 RMS 判断这件事本身是错的） |

---

## 2. 处理思路

呼吸声的两个特征决定了不能只做一件事：

1. **它是低电平、持续几百毫秒的宽带噪声** → 用**向下扩展（gate）**在静音间隙把它压下去；
2. **它和语音频段重叠（200–2kHz）**，单纯 gate 会连带削掉气声辅音 → 再用**轻度谱减（afftdn）**把残余的气声底噪抹平。

两级串联，且**必须放在 EQ 之前**：先降噪再塑形，否则 EQ 的提亮会把气声一起放大。

```
合成输出 → 拼接 → ① gate → ② 谱减 → ③ EQ/压缩 → 响度归一 → 交付
                                    ↑
                              ASR 校验在最后（校验交付物本身）
```

---

## 3. 完整处理链

### 3.1 呼吸抑制（本规范新增）

```bash
agate=threshold=0.050:ratio=3:attack=3:release=120:range=0.45:detection=rms,
afftdn=nr=10:nf=-42,
```

| 参数 | 取值 | 含义 | 调整方向 |
|---|---|---|---|
| `threshold` | 0.050（≈ -26 dBFS） | 低于此电平开始衰减 | 吸气仍明显 → 调到 0.06；字尾发虚 → 降回 0.04 |
| `ratio` | 3 | 向下扩展比例 | 越大压得越狠；超过 4 会听出"抽气感" |
| `attack` | 3 ms | 起控速度 | 太小会把字头吃掉，保持 3–5 |
| `release` | 120 ms | 释放速度 | 太小会断续，100–200 之间 |
| `range` | 0.45 | 最大衰减量（约 -7 dB） | 想更干净可到 0.35（衰减更多），但风险上升 |
| `detection` | rms | 用电平均值检测，比峰值稳 | 一般不改 |
| `afftdn nr` | 10 | 谱减强度（dB） | 6–12 之间；超过 15 会发闷、出"水声" |
| `afftdn nf` | -42 | 噪声底估计（dBFS） | 底噪高的录音调到 -38，干净的调到 -46 |

### 3.2 EQ 与动态（既有）

```bash
highpass=f=80:poles=2,
equalizer=f=180:t=q:w=1.0:g=-2.5,
equalizer=f=420:t=q:w=1.0:g=-1.5,
equalizer=f=3200:t=q:w=1.2:g=2.0,
equalizer=f=7000:t=q:w=2.0:g=-2.0,
deesser=i=0.35:m=0.5:f=0.5,
acompressor=threshold=-18dB:ratio=2.5:attack=8:release=180:makeup=2,
loudnorm=I=-16:TP=-1.5:LRA=11,
alimiter=limit=0.95
```

| 环节 | 作用 |
|---|---|
| highpass 80Hz | 去低频隆隆声、桌面震动 |
| 180Hz -2.5dB | 收胸腔闷响 |
| 420Hz -1.5dB | 收浑浊（"盒音"） |
| 3200Hz +2dB | 提清晰度与咬字 |
| 7000Hz -2dB | 压齿音区 |
| deesser | 齿音动态抑制（在 EQ 之后才准） |
| acompressor 2.5:1 | 轻度压缩，句间更稳 |
| loudnorm I=-16 TP=-1.5 | 统一到投放标准（B 站/网页） |
| alimiter 0.95 | 防削波 |

**实测结果**：原始 -17.3 LUFS / 0.0 dBTP → 成品 -15.6 LUFS / -1.0 dBTP。

---

## 4. 可直接使用的代码

### 4.1 单文件处理（Python）

```python
import subprocess
from pathlib import Path

BREATH = (
    "agate=threshold=0.050:ratio=3:attack=3:release=120:range=0.45:detection=rms,"
    "afftdn=nr=10:nf=-42,"
)
EQ = (
    "highpass=f=80:poles=2,"
    "equalizer=f=180:t=q:w=1.0:g=-2.5,"
    "equalizer=f=420:t=q:w=1.0:g=-1.5,"
    "equalizer=f=3200:t=q:w=1.2:g=2.0,"
    "equalizer=f=7000:t=q:w=2.0:g=-2.0,"
    "deesser=i=0.35:m=0.5:f=0.5,"
    "acompressor=threshold=-18dB:ratio=2.5:attack=8:release=180:makeup=2,"
    "loudnorm=I=-16:TP=-1.5:LRA=11,"
    "alimiter=limit=0.95"
)

def polish(src: str, dst: str, sample_rate: int = 24000, breath: bool = True) -> None:
    """对合成音频做呼吸抑制 + EQ + 响度归一。输入输出均为 wav。"""
    chain = (BREATH if breath else "") + EQ
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", src, "-af", chain,
         "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le", dst, "-y"],
        check=True,
    )
```

### 4.2 批量：多段合成后统一处理再拼接

```python
import subprocess, tempfile, pathlib

def build_track(segments, out_path, gap_seconds=0.7, sample_rate=24000):
    """segments: [(raw_wav_path, ...)]，每段先单独处理，再按静音间隔拼接。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    polished = []
    for i, seg in enumerate(segments):
        dst = tmp / f"p{i}.wav"
        polish(str(seg), str(dst), sample_rate)
        polished.append(dst)

    gap = tmp / "gap.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-t", str(gap_seconds),
                    "-i", f"anullsrc=r={sample_rate}:cl=mono",
                    "-c:a", "pcm_s16le", str(gap), "-y"], check=True)

    lines = []
    for i, p in enumerate(polished):
        lines.append(f"file '{p.as_posix()}'")
        if i < len(polished) - 1:
            lines.append(f"file '{gap.as_posix()}'")
    lst = tmp / "list.txt"
    lst.write_text("\n".join(lines), encoding="utf-8")

    subprocess.run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", out_path, "-y"], check=True)
```

**注意**：逐段处理再拼接，比"先拼一条长轨再整体处理"更好——gate 的阈值检测不会被长静音段带偏，响度归一也不会因为段落电平差异被平均掉。

### 4.3 命令行（一次性）

```bash
ffmpeg -i in.wav -af "\
agate=threshold=0.050:ratio=3:attack=3:release=120:range=0.45:detection=rms,\
afftdn=nr=10:nf=-42,\
highpass=f=80:poles=2,\
equalizer=f=180:t=q:w=1.0:g=-2.5,\
equalizer=f=420:t=q:w=1.0:g=-1.5,\
equalizer=f=3200:t=q:w=1.2:g=2.0,\
equalizer=f=7000:t=q:w=2.0:g=-2.0,\
deesser=i=0.35:m=0.5:f=0.5,\
acompressor=threshold=-18dB:ratio=2.5:attack=8:release=180:makeup=2,\
loudnorm=I=-16:TP=-1.5:LRA=11,\
alimiter=limit=0.95" -ar 24000 -ac 1 -c:a pcm_s16le out.wav -y
```

---

## 5. 踩过的坑（别重复走）

| 尝试 | 结果 | 结论 |
|---|---|---|
| 只把 `agate` 阈值调到 0.03（-30dB） | 整体 RMS 从 -17.977 变到 -17.978，几乎无变化 | 呼吸能量占比太小，**用 RMS 判断是否压住呼吸是错的方法** |
| `compand` 在 -45~-28dB 区间做向下扩展 | 同上，RMS 反而略升（-16.8），听感改善有限 | 区间式扩展对短促吸气不敏感，不如 gate |
| 加大 gate 到 ratio 4 以上 | 出现"抽气感"，字尾发虚 | 上限 3–3.5 |
| 谱减 nr 调到 15+ | 声音发闷、有金属水声 | 6–12 之间 |

**唯一可靠的验收方式是「人耳 A/B + ASR 回读」双确认。**

---

## 6. 接入建议（给实现方）

1. **位置**：放在合成完成、写盘之前；如果是分段流式输出，建议**按段处理**再拼接，不要对整条流做。
2. **开关**：给一个配置项（如 `postprocess.breath_guard: true`），默认开启，允许用户关掉。
3. **按音色重调**：不同音色/参考音频的呼吸强度差别很大。`threshold` 与 `afftdn nf` 应按音色做预设，不要全局写死。
4. **采样率**：链路与采样率无关，但 `highpass` 与 `deesser` 的听感在 24k / 48k 下略有差异，48k 时 deesser 可提到 `i=0.4`。
5. **性能**：整链在 RTX 2060 机器上处理 112 秒音频耗时 < 2 秒，可忽略。

---

## 7. 验收清单

- [ ] 处理前后同一句 A/B 试听，吸气声减弱且字头字尾完整
- [ ] ASR 整轨回读与原文逐字一致
- [ ] 成品响度 -16 LUFS 左右，真峰值 ≤ -1 dBTP
- [ ] 48k 输出单独试听一次（deesser 参数）
- [ ] 至少用两个不同音色各验一遍
- [ ] 关闭开关时输出与处理前一致（可回归）

---

## 8. 附：语速与处理的配合

语速影响呼吸的密度，调语速后要复听：

| 语境 | `speed_factor` | 说明 |
|---|---|---|
| 调侃、招呼、嫌弃 | 0.95 | 快，吸气被压缩在词间，需 gate 生效更明显 |
| 讲参数、讲架构 | 0.82 | 慢，词间留白变长，吸气更突出 → 这一档最需要压呼吸 |
| 致谢、收尾 | 0.80 | 沉，同理 |

**结论：语速越慢，呼吸抑制越不能省。**
