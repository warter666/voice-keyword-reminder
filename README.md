# Voice Keyword Reminder · 实时语音关键词提醒

[English](#english) | 中文

监听 Windows 系统正在播放的声音(视频 / 直播 / 网课),当出现你关心的关键词时,
自动弹出 Windows 通知并播放提示音。比如直播里主播说「签到」,你会立刻收到提醒。（哈哈并非主播，就是想着远程签到：)）

**100% 本地离线识别**:音频不离开你的电脑,不联网、不上传、不存录音。

## 特性

- **系统声音采集**:WASAPI 环回(loopback)直接捕获扬声器/耳机正在播放的声音,无需麦克风、不受环境噪音干扰
- **本地实时转写**:基于 faster-whisper(CTranslate2 加速),CPU 即可实时运行
- **简繁 + 同音容错**:Whisper 常把「副店长」转写成「副典長」——本工具自动做繁简归一和拼音同音匹配,照样命中
- **多关键词**:逗号分隔随意配置,每个关键词独立冷却时间,不会刷屏
- **配置文件**:所有参数写在 `config.toml`,双击 `start.bat` 即用,命令行可临时覆盖

## 工作原理

```
系统声音 ──WASAPI loopback──> 4 秒滑动窗口(每 2 秒前移)
        ──> 16kHz 单声道 ──> faster-whisper 本地转写
        ──> 繁简归一 + 去标点 ──> 精确匹配 / 拼音同音匹配
        ──> 命中 ──> Windows Toast 通知 + 提示音(冷却 30 秒)
```

## 安装

要求:Windows 10/11,Python 3.11+。

```bash
git clone <本仓库地址>
cd voice_reminder
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 快速开始

```bash
# 1. 查看可监听的回环设备,记住你想监听的那个编号(通常是默认播放设备对应的 [Loopback])
.venv\Scripts\python.exe reminder.py --list-devices

# 2. 把编号填进 config.toml 的 device,并修改 keywords 为你关心的词

# 3. 启动(或直接双击 start.bat)
.venv\Scripts\python.exe reminder.py
```

首次运行会自动从 HuggingFace 下载模型(small 约 460MB,只需一次)。
国内下载慢可先切换镜像:

```bat
set HF_ENDPOINT=https://hf-mirror.com
```

## 配置说明(config.toml)

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `device` | 自动 | 回环设备编号,`--list-devices` 查看;不填跟随系统默认播放设备 |
| `keywords` | `["签到"]` | 关键词列表;繁体转写自动归一。词尾加 `*` 启用拼音同音容错,如 `副店长*` 可命中误转写的「副典长」 |
| `model` | `small` | `tiny` / `base` / `small` / `medium`,越大越准越慢 |
| `cooldown` | `30` | 同一关键词两次提醒的最小间隔(秒) |
| `window` / `step` | `4` / `2` | 识别窗口长度与步进(秒),步进小于窗口时窗口重叠防漏 |
| `pinyin` | `false` | 对**所有**关键词启用拼音同音容错;建议保持关闭、按需给单词加 `*`(同音容错有误报风险,如「千岛湖」会误命中「签到」) |
| `toast` / `beep` | `true` | 通知弹窗 / 提示音开关 |
| `quiet` | `false` | 不打印每段识别文本 |

常用命令行参数(优先级高于配置文件):

```bash
python reminder.py --keyword 签到,抽奖     # 临时换关键词
python reminder.py --model base            # 换轻量模型
python reminder.py --cooldown 10           # 提醒冷却改为 10 秒
python reminder.py --device 35             # 临时换监听设备
python reminder.py --gpu                   # NVIDIA 显卡加速(需 CUDA 版 ctranslate2)
python reminder.py --no-beep --quiet       # 静默值守:只弹通知不出声不刷屏
```

## 常见问题

- **听不到任何识别文本?** 回环设备只捕获"播放到该设备"的声音。确认 `device` 编号对应的正是当前播放音频的输出设备(拔插耳机后编号可能变化,重新 `--list-devices`)。
- **通知不弹出?** 检查 Windows 设置 → 系统 → 通知,确认开启"获取应用通知",且勿开启勿扰模式/专注助手。
- **偶尔漏报?** 直播背景音乐嘈杂或语速快时可能漏。可换 `medium` 模型,或把 `window` 调大到 5-6 秒。
- **误报多?** 关闭 `pinyin` 同音匹配,或把 `cooldown` 调大。
- **CPU 占用高?** 换 `base` 或 `tiny` 模型;静音窗口会自动跳过识别,常态占用已经很低。

## 开机自启(可选)

`Win+R` 输入 `shell:startup` 打开启动文件夹,放入 `start.bat` 的快捷方式即可。
想完全无窗口运行,把快捷方式目标改为:

```
D:\Desktop\voice_reminder\.venv\Scripts\pythonw.exe D:\Desktop\voice_reminder\reminder.py
```

## 隐私

- 识别全部在本机完成(faster-whisper 本地推理),**不上传任何音频或文本**
- 唯一的网络请求是首次运行从 HuggingFace 下载模型
- 不保存任何录音

## 许可证

[MIT](LICENSE)。所用依赖(faster-whisper、PyAudioWPatch、winotify、zhconv、pypinyin)均为 MIT 系开源协议。

---

## English

A Windows utility that listens to whatever is playing on your speakers (videos, live streams, classes) via WASAPI loopback capture, transcribes it locally with faster-whisper, and fires a Windows toast notification + sound the moment your keyword is spoken — e.g. "签到" (check-in) in a livestream. (Haha, I’m not the streamer. I just wanted to sign in remotely.)

Highlights: 100% offline & private (no audio ever leaves your machine), traditional/simplified Chinese normalization plus pinyin homophone-tolerant matching (a mis-transcribed「副典長」still hits the keyword「副店长」), multiple keywords with per-keyword cooldown, and a single `config.toml` + double-click `start.bat` workflow.

Requirements: Windows 10/11, Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe reminder.py --list-devices   # pick your loopback device
# set device & keywords in config.toml, then:
.venv\Scripts\python.exe reminder.py                   # or double-click start.bat
```

If the HuggingFace model download is slow in your region: `set HF_ENDPOINT=https://hf-mirror.com`.

Licensed under [MIT](LICENSE).
