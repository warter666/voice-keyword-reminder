#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时语音关键词提醒(Windows)

监听系统正在播放的声音(视频/直播),用 faster-whisper 本地实时转写,
检测到关键词时弹 Windows 通知并播放提示音。

特性:
- 100% 本地离线识别,不上传任何音频
- 简繁自动归一 + 拼音同音容错(「副典長」也能命中关键词「副店长」)
- 支持配置文件 config.toml,命令行参数可覆盖

关键词配置见 config.toml;首次运行自动从 HuggingFace 下载模型,
国内下载慢可先执行: set HF_ENDPOINT=https://hf-mirror.com

用法示例:
    python reminder.py                       # 读取 config.toml(不存在则用默认值)
    python reminder.py --list-devices        # 列出可监听的回环设备
    python reminder.py --keyword 签到,抽奖   # 临时覆盖关键词(逗号分隔)
"""

import argparse
import queue
import re
import sys
import threading
import time
import tomllib
import winsound
from collections import deque
from math import gcd
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.signal import resample_poly

import pyaudiowpatch as pyaudio
from faster_whisper import WhisperModel

try:
    from zhconv import convert as zh_convert
except ImportError:
    zh_convert = None

try:
    from pypinyin import lazy_pinyin, Style
except ImportError:
    lazy_pinyin = None

TARGET_SR = 16000  # whisper 要求 16kHz 单声道
STRIP_RE = re.compile(r"[\s，。！？、,.!?：:;；]+")
NTFY_BASE = "https://ntfy.sh"  # 测试时可替换

# 管道/重定向下用 UTF-8,避免中文输出报错;真实控制台不受影响
for _s in (sys.stdout, sys.stderr):
    if not _s.isatty():
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def ts() -> str:
    return time.strftime("%H:%M:%S")


# ---------------------------------------------------------------- 文本匹配

def normalize_text(text: str) -> str:
    """去空白标点 + 繁转简 + 转小写,用于关键词比对"""
    t = STRIP_RE.sub("", text)
    if zh_convert:
        t = zh_convert(t, "zh-cn")
    return t.lower()


# 语音识别常混淆的声母组,近音容错时视为等价(如「先到」xian ≈「签到」qian)
CONFUSABLE_INITIALS = (
    {"q", "x", "j"},
    {"z", "zh"}, {"c", "ch"}, {"s", "sh"},
    {"n", "l"}, {"f", "h"}, {"l", "r"},
)


def pinyin_seq(text: str) -> tuple:
    """逐字转(声母,韵母)序列;非汉字以 (字符, 字符) 表示"""
    if lazy_pinyin is None or not text:
        return ()
    out = []
    for ch in text:
        ini = lazy_pinyin(ch, style=Style.INITIALS, strict=False)
        fin = lazy_pinyin(ch, style=Style.FINALS, strict=False)
        i = (ini[0] if ini else "").lower()
        f = (fin[0] if fin else "").lower()
        out.append((i, f) if (i or f) else (ch, ch))
    return tuple(out)


def syllables_equal(a: tuple, b: tuple, fuzzy: bool) -> bool:
    """两音节是否等价:fuzzy 时韵母相同且声母同组(或相同)即算命中"""
    if a == b:
        return True
    if not fuzzy:
        return False
    ai, af = a
    bi, bf = b
    if af != bf:
        return False
    if ai == bi:
        return True
    return any(ai in g and bi in g for g in CONFUSABLE_INITIALS)


def parse_keyword(raw: str):
    """尾部 * 表示该词启用拼音近音容错,如「签到*」可命中「先到」「千道」"""
    fuzzy = raw.endswith("*")
    return (raw[:-1] if fuzzy else raw), fuzzy


def build_matchers(keywords, default_fuzzy: bool) -> list:
    """[(原词, 归一化词, 拼音序列或 None, 是否近音容错)]"""
    matchers = []
    for raw in keywords:
        kw, fuzzy = parse_keyword(raw)
        norm = normalize_text(kw)
        use_py = fuzzy or default_fuzzy
        py = pinyin_seq(norm) if (use_py and norm) else None
        matchers.append((kw, norm, py, bool(fuzzy or default_fuzzy)))
    return matchers


def match_keywords(text_norm: str, matchers: list) -> list:
    """返回命中的原始关键词列表:先精确子串,再拼音(近音)滑动窗口"""
    hits = []
    text_py = None
    for display, norm, py, fuzzy in matchers:
        if norm and norm in text_norm:
            hits.append(display)
            continue
        if py:
            if text_py is None:
                text_py = pinyin_seq(text_norm)
            n = len(py)
            for i in range(len(text_py) - n + 1):
                if all(syllables_equal(text_py[i + j], py[j], fuzzy)
                       for j in range(n)):
                    hits.append(display)
                    break
    return hits


# ---------------------------------------------------------------- 音频处理

def to_mono_float(data: bytes, channels: int) -> np.ndarray:
    x = np.frombuffer(data, dtype=np.int16)
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    return x.astype(np.float32) / 32768.0


def resample_to_16k(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == TARGET_SR:
        return x
    g = gcd(int(sr), TARGET_SR)
    return resample_poly(x, TARGET_SR // g, sr // g).astype(np.float32)


def drop_from_deque(chunks: deque, n: int) -> None:
    """从头部丢弃 n 个采样点"""
    while n > 0 and chunks:
        x = chunks[0]
        if len(x) <= n:
            n -= len(x)
            chunks.popleft()
        else:
            chunks[0] = x[n:]
            n = 0


# ---------------------------------------------------------------- 设备与采集

def list_loopback_devices(p) -> None:
    print("可监听的回环设备(系统声音):")
    for dev in p.get_loopback_device_info_generator():
        print(f"  [{dev['index']}] {dev['name']}  "
              f"channels={dev['maxInputChannels']} rate={int(dev['defaultSampleRate'])}")
    print("把编号填进 config.toml 的 device,或用 --device <编号> 指定")


def pick_default_loopback(p):
    """默认输出设备对应的 WASAPI 回环设备"""
    default_out = None
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    except Exception:
        pass
    if default_out and default_out.get("isLoopbackDevice"):
        return default_out
    if default_out:
        for lb in p.get_loopback_device_info_generator():
            if default_out["name"] in lb["name"]:
                return lb
    for lb in p.get_loopback_device_info_generator():  # 兜底:任意一个回环设备
        return lb
    return None


def capture_worker(audio_q: queue.Queue, meta: dict, stop_evt: threading.Event,
                   device) -> None:
    """后台线程:打开回环流,把音频塞进队列(队列满时丢最旧)"""
    stream = None
    try:
        with pyaudio.PyAudio() as p:
            dev = None
            if isinstance(device, str) and device.strip():
                # 按名称匹配:设备编号会因插拔/重启变化,名字更稳定
                want = device.strip()
                for lb in p.get_loopback_device_info_generator():
                    if want.lower() in lb["name"].lower():
                        dev = lb
                        break
                if dev is None:
                    meta["error"] = (f"找不到名称包含「{want}」的回环设备,"
                                     "用 --list-devices 查看现有设备名")
                    return
            elif device not in (None, ""):
                dev = p.get_device_info_by_index(int(device))
            else:
                dev = pick_default_loopback(p)
            if dev is None:
                meta["error"] = "找不到 WASAPI 回环设备(需要 Windows 且存在输出设备)"
                return
            rate = int(dev["defaultSampleRate"])
            channels = int(dev["maxInputChannels"])
            if channels < 1:
                meta["error"] = f"设备 {dev['name']} 没有可用输入声道"
                return
            meta.update(device=dev["name"], rate=rate, channels=channels)

            def on_audio(in_data, frame_count, time_info, status):
                if audio_q.full():
                    try:
                        audio_q.get_nowait()  # 识别跟不上时丢最旧音频
                    except queue.Empty:
                        pass
                try:
                    audio_q.put_nowait(to_mono_float(in_data, channels))
                except queue.Full:
                    pass
                return (in_data, pyaudio.paContinue)

            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=dev["index"],
                frames_per_buffer=1024,
                stream_callback=on_audio,
            )
            stream.start_stream()
            while not stop_evt.is_set():
                time.sleep(0.1)
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
    finally:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass


# ---------------------------------------------------------------- 提醒与识别

def push_phone(title: str, msg: str, s) -> None:
    """手机推送:ntfy(安卓 App)和/或 PushPlus(微信),后台线程发送不阻塞识别"""
    def _send():
        import json as _json
        import time as _time
        import urllib.parse
        import urllib.request
        if s.ntfy_topic:
            # 境内访问 ntfy.sh 偶发 TLS 断连(SSL EOF),失败自动重试: 间隔 1s/3s,最多 3 次
            payload = _json.dumps({"topic": s.ntfy_topic, "title": title,
                                   "message": msg, "tags": ["bell"],
                                   "priority": 4,  # ntfy 只收数字优先级(4=high),字符串 "high" 会被拒收(HTTP 400)
                                   }).encode("utf-8")
            req = urllib.request.Request(f"{NTFY_BASE}/", data=payload,
                                         headers={"Content-Type": "application/json"})
            last_err = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        resp.read()
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        _time.sleep(1 if attempt == 0 else 3)
            if last_err:
                print(f"[{ts()}] ntfy 推送失败(已重试3次): {last_err}")
            else:
                print(f"[{ts()}] 已推送手机(ntfy/{s.ntfy_topic})")
        if s.pushplus_token:
            qs = urllib.parse.urlencode(
                {"token": s.pushplus_token, "title": title,
                 "content": msg, "template": "txt"})
            url = f"https://www.pushplus.plus/send?{qs}"
            last_err = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url, timeout=10) as resp:
                        resp.read()
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if attempt < 2:
                        _time.sleep(1 if attempt == 0 else 3)
            if last_err:
                print(f"[{ts()}] PushPlus 推送失败(已重试3次): {last_err}")
    threading.Thread(target=_send, daemon=True).start()


def fire_alert(keywords, text, s) -> None:
    if s.beep:
        try:
            winsound.PlaySound("SystemExclamation",
                               winsound.SND_ALIAS | winsound.SND_ASYNC)
        except Exception:
            pass
    if s.toast:
        try:
            from winotify import Notification, audio
            toast = Notification(
                app_id="语音关键词提醒",
                title=f"听到「{'、'.join(keywords)}」!",
                msg=text[-80:] or "",
                duration="short",
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception as e:
            print(f"[{ts()}] 通知发送失败: {e}")
    push_phone(f"听到「{'、'.join(keywords)}」", text[-100:] or "快去签到!", s)


def process_window(model, window: np.ndarray, sr: int, matchers, s, last_hit: dict) -> None:
    rms = float(np.sqrt(np.mean(window * window)))
    if rms < s.silence:  # 静音窗口直接跳过,省 CPU 也避免幻觉
        return
    wav = resample_to_16k(window, sr)
    segments, _info = model.transcribe(
        wav,
        language="zh",
        beam_size=1,
        vad_filter=False,                    # 直播常有背景音乐,VAD 容易误杀,关掉更稳
        condition_on_previous_text=False,    # 不携带上文,避免幻觉累积
        without_timestamps=True,
    )
    text = "".join(seg.text for seg in segments if seg.no_speech_prob < 0.7).strip()
    if not text:
        return
    if zh_convert:  # Whisper 输出简繁混杂,统一转简体再显示/推送
        text = zh_convert(text, "zh-cn")
    if not s.quiet:
        print(f"[{ts()}] {text}")
    hits = match_keywords(normalize_text(text), matchers)
    now = time.time()
    hits = [k for k in hits if now - last_hit.get(k, 0) > s.cooldown]
    if hits:
        for k in hits:
            last_hit[k] = now
        print(f"[{ts()}] *** 检测到关键词: {'、'.join(hits)} ***")
        fire_alert(hits, text, s)


# ---------------------------------------------------------------- 配置与入口

def load_settings(args) -> SimpleNamespace:
    """优先级: 命令行 > config.toml > 内置默认值"""
    cfg = {}
    if args.config:
        path = Path(args.config)
        if not path.exists():
            sys.exit(f"配置文件不存在: {path}")
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
        print(f"[{ts()}] 已加载配置: {path.resolve()}")

    def pick(cli_val, key, default):
        return cli_val if cli_val is not None else cfg.get(key, default)

    if args.keyword is not None:
        keywords = [k.strip() for k in re.split(r"[,，]", args.keyword) if k.strip()]
    elif "keywords" in cfg:
        raw = cfg["keywords"]
        keywords = ([str(k).strip() for k in raw if str(k).strip()]
                    if isinstance(raw, list)
                    else [k.strip() for k in re.split(r"[,，]", str(raw)) if k.strip()])
    else:
        keywords = ["签到"]

    remind_times = []
    for t in (cfg.get("remind_times") or []):
        m = re.match(r"^(\d{1,2}):(\d{2})$", str(t).strip())
        if not m:
            sys.exit(f"remind_times 格式错误: {t}(应为 \"HH:MM\")")
        remind_times.append((int(m.group(1)), int(m.group(2))))

    s = SimpleNamespace(
        keywords=keywords,
        device=pick(args.device, "device", None),
        model=pick(args.model, "model", "small"),
        window=float(pick(args.window, "window", 4.0)),
        step=float(pick(args.step, "step", 2.0)),
        cooldown=float(pick(args.cooldown, "cooldown", 30.0)),
        silence=float(pick(args.silence, "silence", 5e-4)),
        pinyin=bool(cfg.get("pinyin", False)),
        ntfy_topic=str(cfg.get("ntfy_topic", "")).strip(),
        pushplus_token=str(cfg.get("pushplus_token", "")).strip(),
        remind_times=remind_times,
        toast=(not args.no_toast) if args.no_toast is not None else bool(cfg.get("toast", True)),
        beep=(not args.no_beep) if args.no_beep is not None else bool(cfg.get("beep", True)),
        quiet=(args.quiet or bool(cfg.get("quiet", False))),
        gpu=args.gpu,
    )
    if not s.keywords:
        sys.exit("至少提供一个关键词(命令行 --keyword 或 config.toml 的 keywords)")
    if (s.pinyin or any(k.endswith("*") for k in s.keywords)) and lazy_pinyin is None:
        print("提示: 未安装 pypinyin,拼音容错不可用(仅精确匹配)")
    if zh_convert is None:
        print("提示: 未安装 zhconv,繁体转写不会自动归一为简体")
    return s


def main() -> None:
    ap = argparse.ArgumentParser(
        description="实时监听系统声音,检测到关键词时弹通知/提示音",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("--config", default="config.toml",
                    help="配置文件路径(默认读取程序目录下 config.toml,不存在则忽略)")
    ap.add_argument("--keyword", default=None, help="关键词,多个用逗号分隔(覆盖配置文件)")
    ap.add_argument("--model", default=None,
                    help="whisper 模型: tiny/base/small/medium,越大越准越慢")
    ap.add_argument("--device", type=int, default=None, metavar="INDEX",
                    help="回环设备编号(先用 --list-devices 查看)")
    ap.add_argument("--list-devices", action="store_true", help="列出回环设备后退出")
    ap.add_argument("--window", type=float, default=None, help="每次识别的音频窗长(秒)")
    ap.add_argument("--step", type=float, default=None,
                    help="识别步进(秒),小于 window 时窗口重叠,防止词被切断")
    ap.add_argument("--cooldown", type=float, default=None,
                    help="同一关键词两次提醒的最小间隔(秒)")
    ap.add_argument("--silence", type=float, default=None, help="静音阈值(RMS)")
    ap.add_argument("--gpu", action="store_true", help="用 CUDA(NVIDIA 显卡)")
    ap.add_argument("--no-toast", action="store_true", default=None, help="不弹 Windows 通知")
    ap.add_argument("--no-beep", action="store_true", default=None, help="不播放提示音")
    ap.add_argument("--quiet", action="store_true", help="不打印每段识别文本")
    args = ap.parse_args()

    if args.list_devices:
        with pyaudio.PyAudio() as p:
            list_loopback_devices(p)
        return

    # 单实例锁:防止双开导致重复识别、重复通知/推送
    import msvcrt
    lock_path = Path(__file__).with_name("reminder.lock")
    lock_fp = open(lock_path, "w")
    try:
        msvcrt.locking(lock_fp.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        sys.exit("检测到 reminder.py 已在运行(锁文件被占用),请勿双开。\n"
                 "如果确认没有在跑,删除项目目录下的 reminder.lock 后重试。")

    s = load_settings(args)
    matchers = build_matchers(s.keywords, s.pinyin)

    print(f"[{ts()}] 加载模型 {s.model}(首次运行需先下载)...")
    model = WhisperModel(s.model,
                         device="cuda" if s.gpu else "cpu",
                         compute_type="float16" if s.gpu else "int8")

    audio_q: queue.Queue = queue.Queue(maxsize=300)
    meta: dict = {}
    stop_evt = threading.Event()
    th = threading.Thread(target=capture_worker,
                          args=(audio_q, meta, stop_evt, s.device), daemon=True)
    th.start()
    while th.is_alive() and not meta:
        time.sleep(0.05)
    if meta.get("error"):
        stop_evt.set()
        sys.exit(f"采集启动失败: {meta['error']}")

    sr = meta["rate"]
    print(f"[{ts()}] 正在监听: {meta['device']} ({sr}Hz, {meta['channels']}声道)")
    print(f"[{ts()}] 关键词: {' / '.join(s.keywords)}"
          f"   拼音容错: {'开' if s.pinyin else '关'}   Ctrl+C 退出")
    if s.ntfy_topic or s.pushplus_token:
        print(f"[{ts()}] 手机推送: {'ntfy ' + s.ntfy_topic if s.ntfy_topic else ''}"
              f"{' PushPlus' if s.pushplus_token else ''}")
    if s.remind_times:
        print(f"[{ts()}] 定时提醒: "
              + ", ".join(f"{h:02d}:{m:02d}" for h, m in s.remind_times))

    win_n = int(s.window * sr)
    step_n = int(s.step * sr)
    keep_n = max(win_n - step_n, 0)  # 处理完后保留的样本,用于窗口重叠
    chunks: deque = deque()
    total = 0
    last_hit: dict = {}
    fired: set = set()

    try:
        while True:
            # 定时提醒:到点推送「可能是签到时间」(不依赖语音识别)
            now = time.localtime()
            for h, m in s.remind_times:
                key = (now.tm_mday, h, m)
                if now.tm_hour == h and now.tm_min == m and key not in fired:
                    fired.add(key)
                    print(f"[{ts()}] *** 定时提醒: 可能是签到时间 ***")
                    push_phone("签到时间提醒", "按课程安排,现在可能是签到时间", s)
                    if s.beep:
                        try:
                            winsound.PlaySound("SystemExclamation",
                                               winsound.SND_ALIAS | winsound.SND_ASYNC)
                        except Exception:
                            pass

            got_new = False
            try:
                while True:
                    chunks.append(audio_q.get_nowait())
                    total += len(chunks[-1])
                    got_new = True
            except queue.Empty:
                pass
            if meta.get("error"):
                sys.exit(f"\n采集线程出错: {meta['error']}")
            if total < step_n:
                if not got_new:
                    time.sleep(0.05)
                continue

            drop_from_deque(chunks, total - win_n)  # 最多保留 window 秒
            total = min(total, win_n)
            window = np.concatenate(chunks) if chunks else np.zeros(1, np.float32)

            process_window(model, window, sr, matchers, s, last_hit)

            drop_from_deque(chunks, total - keep_n)
            total = min(total, keep_n)
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        th.join(timeout=2)
        print(f"\n[{ts()}] 已退出")


if __name__ == "__main__":
    main()
