# -*- coding: utf-8 -*-
"""ntfy 连接测试:发送一条测试推送,验证服务器连通性与主题订阅是否正确。

用法:
    python test_ntfy.py            # 读取 config.toml 里的 ntfy_topic
    python test_ntfy.py 我的主题    # 临时指定主题(不入库)
"""
import ipaddress
import json
import re
import socket
import sys
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

# 只允许 https + 明确列出的推送服务器,防止把请求发往内网/元数据地址
NTFY_BASE = "https://ntfy.sh"  # 与 reminder.py 保持一致,自建服务器时替换并同步加入白名单
ALLOWED_HOSTS = {"ntfy.sh"}

def _validate(url: str):
    """https + 白名单域名,解析出的 IP 不得落在私网/环回/链路本地"""
    u = urllib.parse.urlparse(url)
    host = u.hostname or ""
    if u.scheme != "https" or host.lower() not in ALLOWED_HOSTS:
        raise ValueError(f"仅允许推送到 {sorted(ALLOWED_HOSTS)},拒绝: {u.scheme}://{host}")
    for _, _, _, _, sockaddr in socket.getaddrinfo(host, u.port or 443):
        ip = ipaddress.ip_address(sockaddr[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast):
            raise ValueError(f"{host} 解析到受限地址 {ip},已阻止请求")

class HTTPSNoRedirect(urllib.request.HTTPSHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 禁止重定向,防止被引到白名单之外

def mask_topic(topic: str) -> str:
    """日志里隐藏主题明文,只显示首尾各2字符"""
    if len(topic) <= 4:
        return "****"
    return f"{topic[:2]}****{topic[-2:]}"

def send_test(topic: str) -> bool:
    payload = json.dumps({"topic": topic,
                          "title": "ntfy 测试",
                          "message": "这是一条测试推送,收到说明连接正常 ✔",
                          "tags": ["white_check_mark"],
                          "priority": 4,  # 数字优先级,字符串 "high" 会被拒收
                          }).encode("utf-8")
    req = urllib.request.Request(f"{NTFY_BASE}/", data=payload,
                                 headers={"Content-Type": "application/json"})
    # 与主程序一致:境内访问 ntfy.sh 偶发 SSL EOF,重试间隔 1s/3s
    for attempt in range(3):
        try:
            _validate(req.full_url)
            opener = urllib.request.build_opener(HTTPSNoRedirect)
            with opener.open(req, timeout=10) as resp:
                resp.read()
            return True
        except urllib.error.HTTPError:
            raise  # HTTP 错误(如 400/403)是服务器明确回应,重试无意义
        except Exception as e:
            print(f"  第 {attempt + 1} 次发送失败: {type(e).__name__}: {e}")
            if attempt < 2:
                time.sleep(1 if attempt == 0 else 3)
    return False

def main() -> int:
    topic = ""
    if len(sys.argv) > 1:
        topic = sys.argv[1].strip()
    else:
        cfg_path = Path(__file__).with_name("config.toml")
        if not cfg_path.exists():
            print("未找到 config.toml,也没有命令行主题。")
            print("用法: python test_ntfy.py <主题名>")
            return 1
        with open(cfg_path, "rb") as f:
            topic = str(tomllib.load(f).get("ntfy_topic", "")).strip()

    if not topic:
        print("ntfy_topic 为空(config.toml),先在手机 ntfy App 订阅一个主题并填入配置。")
        return 1
    # ntfy 主题只允许字母数字、-、_(官方规则),既符合规范也防注入
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
        print("主题名不合法:只允许字母、数字、- 和 _,长度 1~64。")
        return 1

    print(f"服务器: {NTFY_BASE}")
    print(f"主题:   {mask_topic(topic)}")
    print("发送测试推送(最多重试3次)...")
    try:
        ok = send_test(topic)
    except urllib.error.HTTPError as e:
        print(f"✘ 服务器拒绝(HTTP {e.code}): {e.reason}")
        print("  400 通常是请求体格式问题;确认 topic 命名合法(不含空格/特殊字符)。")
        return 1
    if ok:
        print("✔ 推送成功!请检查手机 ntfy App 是否收到通知。")
        print("  如果服务器返回成功但手机没收到,检查:App 是否订阅了同一主题、是否关闭了电池优化/网络。")
        return 0
    print("✘ 推送失败:检查网络(境内可尝试代理),或把 NTFY_BASE 换成自建服务器。")
    return 1

if __name__ == "__main__":
    sys.exit(main())
