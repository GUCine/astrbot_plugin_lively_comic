"""群漫畫取話題前看圖、寫分鏡時給原話（10-31 用戶定「兩個都做」）。

10-31 試畫桐群（30000001）：小兔崽崽 13:47 發了一張互聯網行業收入統計圖，接著說「24w？？？」「人均2w收入吗」；
14:14 阳光开朗小女孩說基金全綠。群分析插件只看得到「[图片]」那幾個字（圖整段沒了），又把隔半小時、不相干的兩段
併成一個話題「基金亏损与互联网薪资」，分鏡只拿到摘要，畫成一件事。現在：
- 有人接話的圖（發出後 SEE_WINDOW 秒內有人說了話、或引用了它；表情包不算）用看圖模型各寫一句，當成一條
  「[图片：…]」放進聊天記錄，再交給群分析插件取話題；一天每個群最多 SEE_MAX 張，看過的照消息 ID 記下來不再看
- 10-31 晚起白天邊收邊看（用戶定）：開著群漫畫的群收到圖（表情包不算）就排隊，背景一張一張看，記在同一個檔；
  大群一天一兩百張圖，照「有人接話」只挑得到四十張（收入統計圖排第一百名），晚上取話題時當天看過的全用上，
  晚上只補看還沒看過、有人接話的那幾張
- 寫分鏡時每個話題附上相關的原話（照話題的字找、前後各帶幾句、標時間，不相連的段用「……」隔開），
  她對照原話挑真正連在一起的那段畫
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import aiohttp

from .phone import jpeg_bytes

SEE_MAX = 40  # 一天每個群最多看幾張（10-31 桐群一天有人接話的圖超過 24 張，收入統計圖排不進去）
SEE_WINDOW = 180  # 發圖後多少秒內有人說話算有人接話（別人說一句算 1、發圖的人自己說算 0.5）
SEE_PAR = 4  # 同時看幾張
SEE_SECS = 150  # 看圖這步最多花多久，到點沒看完的就算了
SEE_KEEP = 3 * 86400  # 看過的記多久
SEE_ASK = ("这是群聊里有人发的一张图。用一句话（40 字以内）说清楚图里是什么；图上有标题、数字、关键的字就照写，"
           "是截图就说是什么的截图。不评价、不猜谁发的。只输出这一句。")
WATCH_MAX = 300  # 白天排隊等著看的最多幾張，滿了新的先不看（晚上照「有人接話」補）
WATCH_GAP = 2  # 白天看完一張歇幾秒
CHAT_CTX = 3  # 原話裡命中的那句前後各帶幾句
CHAT_MAX = 30  # 每個話題最多帶幾句原話


def _kind(c) -> str:
    t = getattr(c, "type", "")
    return str(getattr(t, "value", t))


def _text(m) -> str:
    return str(getattr(m, "text_content", "") or "").strip()


def all_images(raw: list, skip: set) -> list[tuple[str, str, object]]:
    """當天所有的圖（群分析插件已經把表情包分出去了）：[(消息 ID, 圖連結, 那條消息)]"""
    out = []
    for m in raw:
        if str(getattr(m, "sender_id", "") or "") in skip:
            continue
        urls = [c.url for c in getattr(m, "contents", ()) or () if _kind(c) == "image" and getattr(c, "url", "")]
        mid = str(getattr(m, "message_id", "") or "")
        if urls and mid:
            out.append((mid, urls[0], m))
    return out


def pick(raw: list, skip: set) -> list[tuple[str, str, object]]:
    """有人接話的圖：[(消息 ID, 圖連結, 那條消息)]，接話的人多的在前，最多 SEE_MAX 張"""
    scored = []
    for i, m in enumerate(raw):
        sid = str(getattr(m, "sender_id", "") or "")
        if sid in skip:
            continue
        urls = [c.url for c in getattr(m, "contents", ()) or () if _kind(c) == "image" and getattr(c, "url", "")]
        if not urls:
            continue
        mid, ts = str(getattr(m, "message_id", "") or ""), int(getattr(m, "timestamp", 0) or 0)
        n = 0
        for m2 in raw[i + 1:]:
            if int(getattr(m2, "timestamp", 0) or 0) - ts > SEE_WINDOW:
                break
            if _text(m2):  # 發圖的人自己接著說也算（10-31 收入統計圖是發圖的人自己說「人均2w收入吗」）
                n += 1 if str(getattr(m2, "sender_id", "")) != sid else 0.5
        n += sum(3 for m2 in raw if mid and str(getattr(m2, "reply_to_id", "") or "") == mid)
        if n:
            scored.append((n, ts, mid, urls[0], m))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(mid, url, m) for _, _, mid, url, m in scored[:SEE_MAX] if mid]


class Seer:
    """看圖：照消息 ID 記在 plugin_data/…/seen_imgs.json"""

    def __init__(self, plugin):
        self.p = plugin

    @property
    def file(self) -> Path:
        return self.p.dir / "seen_imgs.json"

    def _load(self) -> dict:
        """白天邊看邊記、晚上也在記：同一份放在插件身上（_img_seen），只在第一次從檔案讀"""
        d = getattr(self.p, "_img_seen", None)
        if d is None:
            try:
                d = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {}
            except Exception:
                d = {}
            self.p._img_seen = d
        now = time.time()
        for k in [k for k, v in d.items() if now - float(v.get("ts", 0)) >= SEE_KEEP]:
            d.pop(k, None)
        return d

    def _save(self, d: dict):
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.file)

    def known(self, mids) -> dict[str, str]:
        d = self._load()
        return {m: d[m]["d"] for m in mids if d.get(m, {}).get("d")}

    def _prov(self):
        s = self.p.s
        return s.provider("look_provider_id" if s.get("look_provider_id") else "storyboard_provider_id")

    async def _one(self, prov, mid: str, url: str) -> str:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(url, headers={"User-Agent": "Mozilla/5.0"}) as r:
                data = await r.read() if r.status == 200 else b""
        data = jpeg_bytes(data) if len(data) > 200 else None
        if not data:
            raise RuntimeError("图下载不到")
        from io import BytesIO
        from PIL import Image
        d = self.p.dir / "seen"
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{re.sub(r'[^0-9A-Za-z_-]', '', mid)[:40] or 'x'}.jpg"
        with Image.open(BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail((1024, 1024))
            im.save(f, "JPEG", quality=88)
        try:
            resp = await asyncio.wait_for(prov.text_chat(prompt=SEE_ASK, image_urls=[str(f)]), timeout=60)
        finally:
            f.unlink(missing_ok=True)
        out = re.sub(r"\s+", " ", str(getattr(resp, "completion_text", "") or "")).strip().strip("「」\"")
        return out[:80]

    async def describe(self, items: list[tuple[str, str, object]]) -> dict[str, str]:
        """{消息 ID: 一句描述}；看不到的不寫"""
        if not items:
            return {}
        cache = self._load()
        out = {mid: cache[mid]["d"] for mid, _, _ in items if cache.get(mid, {}).get("d")}
        todo = [(mid, url) for mid, url, _ in items if mid not in out]
        prov = self._prov() if todo else None
        if prov is not None:
            sem = asyncio.Semaphore(SEE_PAR)
            errs: list[str] = []

            async def run(mid, url):
                async with sem:
                    try:
                        d = await self._one(prov, mid, url)
                        if d:
                            out[mid] = d
                            cache[mid] = {"d": d, "ts": int(time.time())}
                    except Exception as e:
                        errs.append(str(e)[:60] or type(e).__name__)
            tasks = [asyncio.ensure_future(run(m, u)) for m, u in todo]
            _, late = await asyncio.wait(tasks, timeout=SEE_SECS)
            for t in late:
                t.cancel()
            self._save(cache)
            from astrbot.api import logger
            logger.info(f"[lively_comic] 取话题前看图：{len(items)} 张有人接话，看了 {len(todo)} 张新的，"
                        f"{len(out)} 张有描述" + (f"；没看成 {len(errs) + len(late)} 张（{errs[0] if errs else '超时'}）"
                                                    if errs or late else ""))
        return out


def legacy_images(items: list[tuple[str, str, object]], descs: dict[str, str]) -> list[dict]:
    """看過的圖變成群分析插件認得的一條條消息（只有字）"""
    out = []
    for mid, _, m in items:
        if mid in descs:
            out.append({"time": int(getattr(m, "timestamp", 0) or 0),
                        "sender": {"user_id": str(getattr(m, "sender_id", "")), "nickname": str(getattr(m, "sender_name", "") or ""),
                                   "card": str(getattr(m, "sender_card", "") or "")},
                        "message": [{"type": "text", "data": {"text": f"[图片：{descs[mid]}]"}}]})
    return out


def chat_lines(raw: list, descs: dict[str, str], skip: set) -> list[dict]:
    """當天的原話（給分鏡對照）：[{ts, qq, name, text}]，圖換成看到的那句，沒看的圖寫「[图片]」"""
    out = []
    for m in raw:
        sid = str(getattr(m, "sender_id", "") or "")
        if sid in skip:
            continue
        text = _text(m)
        mid = str(getattr(m, "message_id", "") or "")
        if mid in descs:
            text = (text + " " if text else "") + f"[图片：{descs[mid]}]"
        elif not text and any(_kind(c) == "image" for c in getattr(m, "contents", ()) or ()):
            text = "[图片]"
        ats = [str(getattr(c, "at_user_id", "") or "") for c in getattr(m, "contents", ()) or () if _kind(c) == "at"]
        if text and ats:  # @ 了誰要留著：10-31「你别玩了」是 @张顺平 說遊戲，丟了 @ 就被當成勸人別買基金
            text = " ".join(f"@{q}" for q in ats if q) + " " + text
        if text:
            out.append({"ts": int(getattr(m, "timestamp", 0) or 0), "qq": sid, "mid": mid,
                        "re": str(getattr(m, "reply_to_id", "") or ""),
                        "name": str(getattr(m, "sender_card", "") or getattr(m, "sender_name", "") or sid)[:10],
                        "text": text[:120]})
    return out


def _grams(t: str) -> set:
    t = re.sub(r"[^\w一-鿿]", "", t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def topic_chat(lines: list[dict], topic_text: str, who: set, name_of) -> str:
    """這個話題相關的原話：命中話題字詞的句子（說話的是參與者的更容易算），前後各帶 CHAT_CTX 句，
    不相連的段之間寫「……」；每句「時:分 名字：內容」。name_of(qq, 原名) → 分鏡裡的稱呼"""
    if not lines:
        return ""
    want = _grams(topic_text)
    df: dict[str, int] = {}
    gl = [_grams(x["text"]) for x in lines]
    for g in gl:
        for x in g:
            df[x] = df.get(x, 0) + 1
    common = {x for x, n in df.items() if n > max(8, len(lines) * 0.05)}
    want -= common
    hit = [i for i, g in enumerate(gl) if len(g & want) >= (1 if lines[i]["qq"] in who else 2)]
    if not hit:
        return ""
    keep: set[int] = set()
    for i in hit:
        keep.update(range(max(0, i - CHAT_CTX), min(len(lines), i + CHAT_CTX + 1)))
    idx = sorted(keep)
    if len(idx) > CHAT_MAX:  # 太多就留命中最多的那幾段附近
        best = sorted(hit, key=lambda i: -len(gl[i] & want))[:CHAT_MAX // (2 * CHAT_CTX + 1) + 1]
        keep = set()
        for i in best:
            keep.update(range(max(0, i - CHAT_CTX), min(len(lines), i + CHAT_CTX + 1)))
        idx = sorted(keep)[:CHAT_MAX]
    qq_name = {x["qq"]: x["name"] for x in lines}
    mid_qq = {x.get("mid"): x["qq"] for x in lines if x.get("mid")}

    def said(x) -> str:
        t = re.sub(r"@(\d{5,})", lambda m: "@" + name_of(m.group(1), qq_name.get(m.group(1), m.group(1))), x["text"])
        to = mid_qq.get(x.get("re"))
        return (f"（回 {name_of(to, qq_name.get(to, to))}）" if to else "") + t
    out, prev = [], None
    for i in idx:
        if prev is not None and i != prev + 1:
            out.append("  ……")
        x = lines[i]
        out.append(f"  {time.strftime('%H:%M', time.localtime(x['ts']))} {name_of(x['qq'], x['name'])}：{said(x)}")
        prev = i
    return "\n".join(out)


def live_images(event) -> list[tuple[str, str]]:
    """白天收到的這條消息裡的圖（不含表情包、商城表情）：[(消息 ID, 圖連結)]，讀 NapCat 原始消息"""
    raw = getattr(event.message_obj, "raw_message", None)
    try:
        segs = raw.get("message") if raw is not None else None
    except Exception:
        segs = None
    mid = str(getattr(event.message_obj, "message_id", "") or "")
    out = []
    for seg in segs if isinstance(segs, list) and mid else []:
        if not isinstance(seg, dict) or seg.get("type") != "image":
            continue
        data = seg.get("data") or {}
        sub = str(data.get("sub_type", data.get("subType", "")))
        url = str(data.get("url") or "")
        if sub == "1" or "表情" in str(data.get("summary") or "") or "gxh.vip.qq.com" in url or not url.startswith("http"):
            continue
        out.append((mid, url))
        break  # 一條消息看第一張就夠（晚上也只用第一張）
    return out


class Watcher:
    """白天邊收邊看：收到就排隊，背景一張一張看，記進 Seer 那份"""

    def __init__(self, plugin):
        self.p = plugin
        self.q: asyncio.Queue = asyncio.Queue(maxsize=WATCH_MAX)
        self.seer = Seer(plugin)
        self.n = 0

    def offer(self, mid: str, url: str):
        if self.seer.known([mid]):
            return
        try:
            self.q.put_nowait((mid, url, time.time()))
        except asyncio.QueueFull:
            pass

    async def run(self):
        from astrbot.api import logger
        while True:
            mid, url, t0 = await self.q.get()
            try:
                if time.time() - t0 > 3600 or self.seer.known([mid]):  # 排太久的圖連結多半過期了
                    continue
                prov = self.seer._prov()
                if prov is None:
                    continue
                d = await self.seer._one(prov, mid, url)
                if d:
                    cache = self.seer._load()
                    cache[mid] = {"d": d, "ts": int(time.time())}
                    self.seer._save(cache)
                    self.n += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"[lively_comic] 白天看图没看成：{e}")
            await asyncio.sleep(WATCH_GAP)
