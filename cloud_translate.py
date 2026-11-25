"""Official Microsoft Translator v3 and Google Cloud Translation Basic v2 clients."""

from collections import Counter
import html
from html.parser import HTMLParser
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SERVICES = {"ollama": "本机 Ollama", "microsoft": "微软翻译 · Azure",
            "google": "Google Cloud 翻译", "config": "PDF2Zh 配置文件"}
KEYS = {"microsoft": "AZURE_TRANSLATOR_KEY", "google": "GOOGLE_TRANSLATE_API_KEY"}
TOKEN = re.compile(r"</?b\d+>|\{v\d+\}|<v\d+\s*/>")


class DecodedText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def cloud_text(provider, source, target, text):
    key = os.environ.get(KEYS[provider], "").strip()
    if not key:
        raise ValueError(f"请填写 {SERVICES[provider]} 的 API 密钥")
    tokens = TOKEN.findall(text)
    if tokens:
        pieces = TOKEN.split(text)
        body = html.escape(pieces[0])
        for token, piece in zip(tokens, pieces[1:]):
            body += '<span class="notranslate" translate="no">' + html.escape(token) + "</span>" + html.escape(piece)
    else:
        body = text
    fmt = "html" if tokens else "text"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if provider == "microsoft":
        lang = {"zh-CN": "zh-Hans"}
        query = {"api-version": "3.0", "from": lang.get(source, source), "to": lang.get(target, target),
                 "textType": fmt if tokens else "plain"}
        url = "https://api.cognitive.microsofttranslator.com/translate?" + urlencode(query)
        headers["Ocp-Apim-Subscription-Key"] = key
        if region := os.environ.get("AZURE_TRANSLATOR_REGION", "").strip():
            headers["Ocp-Apim-Subscription-Region"] = region
        payload = [{"Text": body}]
    else:
        url = "https://translation.googleapis.com/language/translate/v2"
        headers["X-Goog-Api-Key"] = key
        payload = {"q": body, "source": source, "target": target, "format": fmt}
    req = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers)
    try:
        with urlopen(req, timeout=45) as response:
            data = json.load(response)
        result = (data[0]["translations"][0]["text"] if provider == "microsoft"
                  else data["data"]["translations"][0]["translatedText"])
        if not isinstance(result, str) or not result.strip():
            raise ValueError("服务返回空译文")
    except HTTPError as exc:
        hint = {400: "请检查语言和请求参数", 401: "请检查密钥和资源区域",
                403: "请检查服务启用状态、密钥权限、区域或额度", 429: "请求过于频繁或额度已用完"}
        raise ValueError(f"{SERVICES[provider]} HTTP {exc.code} · {hint.get(exc.code, '请稍后再试')}") from None
    except (URLError, TimeoutError) as exc:
        raise ValueError(f"无法连接 {SERVICES[provider]}，请检查网络或代理") from exc
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{SERVICES[provider]} 返回了无法读取的译文") from exc
    if tokens:
        parser = DecodedText()
        parser.feed(result)
        parser.close()
        result = "".join(parser.parts)
        if Counter(TOKEN.findall(result)) != Counter(tokens):
            raise ValueError("翻译服务更改了公式占位符，可改用段落对照模式")
    return result
