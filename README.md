# Voice Keyword Reminder · 实时语音关键词提醒

[English](#english) | 中文

监听 Windows 系统正在播放的声音(视频 / 直播 / 网课),当出现你关心的关键词时,
自动弹出 Windows 通知并播放提示音。比如直播里主播说「签到」,你会立刻收到提醒。（哈哈并非主播，就是想着远程签到：)）

**100% 本地离线识别**:音频不离开你的电脑,不联网、不上传、不存录音。

## 特性

- **系统声音采集**:WASAPI 环回(loopback)直接捕获扬声器/耳机正在播放的声音,无需麦克风、不受环境噪音干扰
- **本地实时转写**:基于 faster-whisper(CTranslate2 加速),CPU 即可实时运行
- **简繁归一 + 近音容错**:识别文本统一转简体显示;词尾加 `*` 后,同音字(「千道」)和声母易混词(「先到」≈「签到」,q/x 等声母组)都能命中
- **多关键词**:逗号分隔随意配置,每个关键词独立冷却时间,不会刷屏
- **手机推送**:命中时同步推送到手机(ntfy / PushPlus),人不在电脑前也能收到
- **定时提醒**:按课程时间表定时推送,语音没听清也能兜底
- **配置文件**:所有参数写在 `config.toml`,双击 `start.bat` 即用,命令行可临时覆盖

## 工作原理

```
系统声音 ──WASAPI loopback──> 4 秒滑动窗口(每 2 秒前移)
        ──> 16kHz 单声道 ──> faster-whisper 本地转写
        ──> 繁简归一 + 去标点 ──> 精确匹配 / 拼音近音匹配
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
| `device` | 自动 | 留空 `""` 跟随系统默认播放设备(推荐);也可写名称片段如 `"耳机"`(按名字找,插拔不变)或编号(插拔后会变,不推荐)。`--list-devices` 查看设备名 |
| `keywords` | `["签到"]` | 关键词列表;繁体转写自动归一。词尾加 `*` 启用拼音近音容错:`签到*` 可命中「千道」(同音)和「先到」(声母 q/x 易混) |
| `model` | `small` | `tiny` / `base` / `small` / `medium`,越大越准越慢;实测体积 small≈464MB、medium≈1.5GB,首次运行自动下载。CPU 实时推荐 `small`(medium 在 CPU 上识别窗可能追不上直播,导致延迟累积) |
| `cooldown` | `30` | 同一关键词两次提醒的最小间隔(秒) |
| `window` / `step` | `4` / `2` | 识别窗口长度与步进(秒),步进小于窗口时窗口重叠防漏 |
| `pinyin` | `false` | 对**所有**关键词启用拼音近音容错;建议保持关闭、按需给单词加 `*`(容错越大误报越多,如「千岛湖」会命中「签到*」) |
| `toast` / `beep` | `true` | 通知弹窗 / 提示音开关 |
| `ntfy_topic` | 空 | 安卓手机推送:装 [ntfy](https://ntfy.sh) App 订阅一个主题,把主题名填入。**主题名要够冷门**(如 `my-secret-7f3k`):ntfy 主题无鉴权,谁订阅同名主题谁就能看到你的推送。**不要把真实主题名发到公开场合/截图里** |
| `pushplus_token` | 空 | 微信推送:关注 PushPlus 公众号获取 token 填入 |
| `remind_times` | 空 | 定时提醒列表如 `["08:00","08:45","09:30"]`,到点推送「可能是签到时间」 |
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

- **听不到任何识别文本?** 回环设备只捕获"播放到该设备"的声音。确认 `device` 对应的正是当前播放音频的输出设备;推荐 `device = ""` 自动跟随默认设备,或用名称片段如 `"耳机"`。
- **通知不弹出?** 检查 Windows 设置 → 系统 → 通知,确认开启"获取应用通知",且勿开启勿扰模式/专注助手。
- **手机收不到推送?** 电脑端每次推送成功会在控制台打印 `已推送手机(ntfy/主题名)`,先看这条日志再查手机端:
  1. 浏览器打开 `https://ntfy.sh/你的主题名` 发条消息——手机能收到说明只是电脑端没触发;收不到继续往下查
  2. ntfy App 订阅的主题名与 `ntfy_topic` **完全一致**(区分大小写、不能有多余空格),服务器选默认 ntfy.sh
  3. 手机系统设置里允许 ntfy 后台自启/无限制省电(国产 ROM 的省电策略容易杀后台)
  4. 换 Wi-Fi/流量交叉试一次,排除网络对 ntfy.sh 的拦截
- **偶尔漏报?** 直播背景音乐嘈杂或语速快时可能漏。可换 `medium` 模型,或把 `window` 调大到 5-6 秒。
- **识别延迟越来越大?** CPU 跑 `medium` 可能追不上直播音频(队列会自动丢最旧音频)。换回 `small`,或开 `--gpu`。
- **误报多?** 关闭 `pinyin` 同音匹配,或把 `cooldown` 调大。
- **CPU 占用高?** 换 `base` 或 `tiny` 模型;静音窗口会自动跳过识别,常态占用已经很低。
- **提示"已在运行/请勿双开"?** 程序用锁文件防双开(双开会重复通知)。确认没有实例后删除项目目录下 `reminder.lock` 再启动。

## 手机端 ntfy 配置(安卓)

电脑端只需在 `config.toml` 填 `ntfy_topic`;手机端按以下步骤一次性配置:

1. **安装**:应用商店搜「ntfy」或 [F-Droid](https://f-droid.org/packages/io.heckel.ntfy/) 安装
2. **选主题名**:想一个**别人猜不到的名字**(如 `my-secret-7f3k`)。ntfy 主题无鉴权,
   任何订阅同名主题的人都能看到你的推送;主题名也不要发到公开场合或截图里
3. **订阅**:ntfy App → `+` → 订阅 → 服务器保持默认 `ntfy.sh` → 输入你的主题名
  订阅主题时需要打开“低功耗模式下仍实时推送”
5. **开启即时交付**(关键):进入该订阅 → 右上角设置 → 打开 **「即时交付 / Instant delivery」**。
   开启后 App 用常驻连接收推送,不依赖谷歌服务,国内可用;不开则锁屏后收不到、
   要等手动打开 App 才收到积压消息
6. **防杀后台**:
   - 系统设置 → 应用 → ntfy → 省电策略 → **无限制**(各 ROM 名称略有差异)
   - 多任务界面把 ntfy **下拉锁定**,防止一键清理
   - 允许「自启动」和「后台弹出界面」(如有该选项)
7. **验证**:
   - 电脑浏览器打开 `https://ntfy.sh/你的主题名` 发一条消息,手机应立即弹出
   - 电脑端跑起本程序后,命中关键词会推送,同时控制台打印 `已推送手机(ntfy)`;
     若控制台有这条而手机没弹,按上面 4、5 两步检查,或用订阅列表里的
     「测试通知」按钮排查

> 微信备用通道:PushPlus 推送走微信服务通知,不受 App 后台存活影响,更稳。
> 关注「pushplus」公众号取 token 填入 `pushplus_token` 即可,两者可同时启用。

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
