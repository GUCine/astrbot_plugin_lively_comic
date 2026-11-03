"""群友定做自己的虛擬形象（lively_avatar，10-27 用戶定）。

- 只能給正在說話的這個人做 TA 自己的；看得到別人的，改不了別人的。例外（10-29 用戶定）：〈主人〉說話的聊天裡寫了 qq，
  准备、确认、取消都算那個人的，〈主人〉的確認就算數、不受每人一次限制（算〈主人〉放行）；沒給新描述、新圖就沿用 TA 之前準備過的那份
  （TA 準備過沒確認、過了時限的那份留著不刪，就為這個；TA 自己重新準備沒給新的也沿用）
- 兩步：准备（收 TA 在這個聊天裡剛發的、或這條引用的圖，最多 3 張，加上描述，回一份摘要給她）→ TA 本人在之後的消息裡確認了，
  她再調确认才畫（同一條消息裡不算，准备後 PENDING_TTL 內有效）；畫好的三視圖發到這個聊天、存下，以後畫到 TA 就用它
- 畫法（10-27 用戶定）：先照 TA 的圖和描述在群漫畫裡畫一格 TA（<QQ>_panel.png，畫風參考在 avatars/style/），再照那格畫三視圖；
  粗黑線、平塗飽和、硬陰影、細節少。兩張都算進每天畫圖的張數
- 每人一次；做過的再做要主人同意（放行，只有主人說的才算）。沒畫成不算次數。算進 comic 每天畫圖的張數
- 三視圖畫好、發出去以後，在背景照它再畫一張半身像當印象卡的卡面（<QQ>_card.png，10-27 用戶定）；也算一張。
  沒畫成不影響形象本身，bond 畫卡時從三視圖裁
- 怎麼問、怎麼跟 TA 說都是她定，工具只講事實
存在資料目錄 avatars/：<QQ>.png 和 avatars.json（made：做好的；pending：准备了還沒確認的；allow：主人放行的）
"""
from __future__ import annotations

import asyncio
import io
import re
import time
from datetime import datetime, timedelta, timezone

from pathlib import Path

import aiohttp
from astrbot.api import logger

from . import phone as phone_mod

TZ = timezone(timedelta(hours=8))
PENDING_TTL = 30 * 60
RECENT = 30 * 60          # TA 多久內發的圖算「剛發的」
MAX_IMGS = 3
HISTORY = 40
BLOCKED = ("萝莉", "幼女", "幼童", "小学生", "儿童", "未成年", "loli", "child", "kid", "underage", "minor")
# 畫風（10-27 用戶定，以後定做都照這個）：粗黑線、輪廓清楚；平塗、飽和、對比強；陰影硬而深；細節少（有點吊帶襪天使的感覺）
AVATAR_STYLE = ("chibi characters about three heads tall; very thick, solid black outlines with a clear silhouette; "
                "flat, highly saturated colors with strong contrast; hard-edged deep cel shadows, no soft gradients, no pastel "
                "washes; simplified shapes and few details (no small ornaments, chains, lace, sparkles or glitter); a bold, punchy "
                "western-cartoon-influenced anime look, like a modern TV cartoon")
# 畫風參考圖放在 avatars/style/（照檔名順序，換圖不用重啟；10-27 放的是祈照群漫畫做的那格和三視圖），空的就用〈我〉的 Q 版三視圖
STYLE_DIR = "style"
STYLE_EXT = (".png", ".jpg", ".jpeg", ".webp")
# 第一步：照 TA 給的圖和描述，先在群漫畫裡畫一格 TA（直接畫三視圖容易跟著參考圖原來的畫法走，10-27 試過）
AVATAR_STYLE_REF = ("{style_refs} only the art style reference (line weight, coloring, shading, proportions): do not copy "
                    "their characters, outfits, story or text.\n")
AVATAR_PANEL_PROMPT = (
    "Draw one single comic panel (one square frame, like one panel cut out of our group chat comic) showing only 「{name}」, "
    f"in this art style: {AVATAR_STYLE}.\nHow 「{{name}}」 looks: {{desc}}\n"
    "Full body, standing in a simple everyday pose with an expression that fits them, a plain light background. "
    "A small white name tag above the head reading 「{name}」, the way the comic labels its characters. "
    "Only this one character, no speech bubbles, no other text. A young adult, fully clothed, nothing explicit.")
# 第二步：照那一格做三視圖
AVATAR_PROMPT = (
    "Image 1 is a panel from our group chat comic. The character labeled 「{name}」 is the one to draw. Make a character "
    "reference sheet of exactly this character, in exactly the same art style as this comic panel: the same chibi proportions, "
    "the same face, hair, eyes, outfit, shoes and accessories. Keep the lines very thick and black, the colors flat, saturated "
    "and high-contrast, the shadows hard and deep, and the details few. Three full-body views in one row on a plain white "
    "background: front, side and back, standing naturally. Only this one character, no other characters, no props, no "
    "speech bubbles, no name tag, no text, no background.")
AVATAR_CARD_PROMPT = (  # 和本倉庫 server/batch_avatars_comic_1027.py（LOOK=bold）一樣
    "Image 1 is the character reference sheet of 「{name}」 (front, side and back views of one character). "
    "Draw this same character as a single portrait for a profile card: exactly the same hair, face, eyes, outfit, accessories "
    "and features, from the chest up, facing the viewer with a small natural expression that fits them, centered horizontally, "
    "the face a little above the middle of the picture with some room above the head, shoulders reaching near the bottom edge. "
    "Plain background: a soft gradient in one or two light colors from the character's palette with a few small round "
    "bokeh dots; no scenery, no other characters, nothing in front of the character. "
    "Exactly the same art style as the reference sheet: the same chibi face, thick dark outlines, cel shading and colors. "
    "Very thick black lines, flat saturated colors, hard deep shadows, few details; the background gradient may be a "
    "bold color instead of a light one. "
    "A young adult, fully clothed, nothing explicit. No text, no labels, no names, no frame, no border.")
AVATAR_QQ_REF = ("Image 1 is the QQ avatar of 「{name}」: follow it for how the avatar looks (if it is a photo of a real person, "
                 "turn it into this comic style; if it is not a person, take its colors and subject and design a person from "
                 "them).\n")
AVATAR_REFS = ("Images 1 to {n} are references 「{name}」 gave for how the avatar should look: follow them (if a reference is a photo "
               "of a real person, turn it into this comic style; if it is not a person, take its colors and subject). Take only the "
               "design from them, not their art style.\n")

# 投喂滿檔的合照卡面（10-29 用戶定：投喂累計 ≥150 自動畫一張 TA 的虛擬形象和〈我〉的合照，照〈主人〉那張卡面的畫法；
# 存進 bond 的 card_bg/<QQ>.webp，印象卡、面板〈卡〉都換成它）
DUO_WHO = ("Image 1 is Xiaofeiyu: a cute chibi whale girl with long wavy hair fading from deep navy to light blue, one ahoge, a white "
           "maid headdress with a light-blue bow, dark navy whale-fin ears, one navy whale tail with a two-lobed fluke, a navy maid "
           "dress with a white apron. Image 2 is 「{name}」{how}. Draw both clearly recognizable, keeping each one's face, hair "
           "and outfit, in one consistent soft illustration style, {name_short} as a young adult about Xiaofeiyu's age. ")
DUO_HOW_MADE = " (their own character reference sheet: front, side and back views of the same character)"
DUO_HOW_QQ = (" (their QQ avatar: if it is a photo of a real person, turn it into this illustration style; if it is not a person, "
              "take its colors and subject and design a young adult from them)")
DUO_SCENE = ("Scene: a quiet seaside window at golden hour, like a photo the two of them took together. They sit side by side, "
             "Xiaofeiyu leaning happily against 「{name}」's shoulder with her whale tail curled around, both looking at the viewer "
             "with warm, slightly shy smiles. ")
DUO_STYLE = ("Minimalist, elegant, high-end collectible card illustration in portrait orientation. Soft gouache and watercolor "
             "texture, refined muted palette, generous negative space, gentle cinematic light. The two characters together take "
             "about one third of the image height, centered horizontally, their heads at about one fifth from the top; the lower half "
             "of the image is calm, simple and softly graded, with no characters or objects. Warm, affectionate mood. "
             "Both fully clothed, nothing explicit. No text, no letters, no logo, no frame, no border, no UI.")
DUO_LOOK = "〈我〉和 TA 的合照：海边窗前，〈我〉靠在 TA 肩上，两个人一起看着镜头笑"


def _pics(segs) -> list[str]:
    out = []
    for s in segs or []:
        if isinstance(s, dict) and s.get("type") == "image":
            d = s.get("data") or {}
            for k in ("url", "file"):
                v = str(d.get(k) or "")
                if v.startswith("http"):
                    out.append(v)
                    break
    return out


def _reply_id(segs) -> str:
    for s in segs or []:
        if isinstance(s, dict) and s.get("type") == "reply":
            return str((s.get("data") or {}).get("id") or "")
    return ""


def _hm(ts) -> str:
    return datetime.fromtimestamp(float(ts or 0), TZ).strftime("%m-%d %H:%M")


class Avatars:
    def __init__(self, plugin):
        self.p = plugin
        self._busy: set[str] = set()

    @property
    def phone(self):
        return self.p.phone

    # ---------- 找 TA 的圖 ----------
    async def _history(self, umo: str) -> list[dict]:
        client = self.p.s.client()
        if client is None:
            return []
        peer = umo.rsplit(":", 1)[-1]
        try:
            if ":GroupMessage:" in umo:
                res = await client.api.call_action("get_group_msg_history", group_id=int(peer), count=HISTORY)
            else:
                res = await client.api.call_action("get_friend_msg_history", user_id=int(peer), count=HISTORY)
        except Exception:
            return []
        return sorted((res or {}).get("messages") or [], key=lambda m: m.get("time", 0), reverse=True)

    async def collect(self, event, qq: str) -> list[tuple[str, str]]:
        """TA 給的圖 [(網址, 哪張)]：這條帶的、這條引用的（引用的是 TA 自己發的才算）、TA 半小時內在這裡發的，最多 MAX_IMGS 張"""
        out: list[tuple[str, str]] = []
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        segs = raw.get("message") if isinstance(raw, dict) else []
        for u in _pics(segs):
            out.append((u, "这条里的图"))
        rid = _reply_id(segs)
        client = self.p.s.client()
        if rid and client is not None:
            try:
                q = await client.api.call_action("get_msg", message_id=int(rid))
            except Exception:
                q = None
            if q and str((q.get("sender") or {}).get("user_id", "")) == qq:
                out += [(u, "这条引用的那张") for u in _pics(q.get("message"))]
        now = time.time()
        for m in await self._history(event.unified_msg_origin):
            if str((m.get("sender") or {}).get("user_id", "")) != qq:
                continue
            if now - m.get("time", 0) > RECENT:
                break
            out += [(u, f"{datetime.fromtimestamp(m.get('time', 0), TZ):%H:%M} 发的那张") for u in _pics(m.get("message"))]
        seen, uniq = set(), []
        for u, w in out:
            key = re.sub(r"[?&]rkey=[^&]*", "", u)
            if key not in seen:
                seen.add(key)
                uniq.append((u, w))
        return uniq[:MAX_IMGS]

    async def _save_pic(self, url: str, path) -> bool:
        if "multimedia.nt.qq.com.cn" in url:  # 這個網域走 https 會憑證出錯（表情包插件也是這樣下）
            url = url.replace("https://", "http://", 1)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                async with s.get(url) as r:
                    data = await r.read() if r.status == 200 else b""
            from PIL import Image
            im = Image.open(io.BytesIO(data)).convert("RGB")
            im.thumbnail((1024, 1024))
            path.parent.mkdir(parents=True, exist_ok=True)
            im.save(path, "JPEG", quality=88)
            return True
        except Exception:
            return False

    # ---------- 工具 ----------
    async def run(self, event, action: str, desc: str = "", images: str = "", qq: str = "", text: str = "",
                  to_ta: bool = False, group: str = "") -> str:
        me = str(event.get_sender_id() or "")
        action = str(action or "").strip()
        if "放行" in action:
            return self._allow(me, qq)
        if ("看" in action or "查" in action) and str(group or "").strip():
            return await self._look_group(str(group))
        if "看" in action or "查" in action:
            return self._look(re.sub(r"\D", "", str(qq or "")) or me)
        who = re.sub(r"\D", "", str(qq or ""))
        for_other = bool(who) and who != me
        if for_other and not self.p.s.is_owner(me):
            return self.p.s.fill("没做：只能给正在跟〈我〉说话的这个人做 TA 自己的；替别人准备、确认要〈主人〉说了才行")
        target = who if for_other else me
        if "取消" in action:
            d = self.phone.avatars()
            had = (d.get("pending") or {}).pop(target, None)
            self.phone.save_avatars(d)
            return "取消了，准备的那份删掉了" if had else "TA 没有在准备的形象"
        if "确认" in action:
            return await self._confirm(event, target, text, by_owner=for_other, to_ta=to_ta)
        if "准备" in action:
            return await self._prepare(event, target, desc, images, by_owner=for_other)
        return "没做：action 写 准备、确认、看、取消 或 放行"

    def _times(self, qq: str) -> tuple[int, bool]:
        d = self.phone.avatars()
        rec = (d.get("made") or {}).get(qq) or {}
        return int(rec.get("count") or 0), qq in (d.get("allow") or {})

    def _can_make(self, qq: str, by_owner: bool = False) -> str:
        if by_owner or self.p.s.is_owner(qq):
            return ""
        n, allowed = self._times(qq)
        if n >= 1 and not allowed:
            rec = (self.phone.avatars().get("made") or {}).get(qq) or {}
            return self.p.s.fill(f"TA 已经做过一次了（{_hm(rec.get('ts'))}），每人一次，再做要〈主人〉同意："
                               "〈主人〉同意了，要〈我〉在〈主人〉说话的聊天里用「放行」写上 TA 的 QQ 才记得下，光说一声这里不知道")
        return ""

    async def _prepare(self, event, me: str, desc: str, images: str, by_owner: bool = False) -> str:
        desc = re.sub(r"\s+", " ", str(desc or "")).strip()[:600]
        why = self._can_make(me, by_owner)
        if why:
            return f"没准备：{why}"
        old = (self.phone.avatars().get("pending") or {}).get(me) or {}  # TA 之前準備過、沒畫的那份（過期的也留著）
        if not desc and old.get("desc"):
            desc = old["desc"]
        if not desc:
            return "没准备：描述是空的（格式：hair / eyes / face / body / outfit / accessories / features / vibe）"
        low = desc.lower()
        bad = [w for w in BLOCKED if w in low]
        if bad:
            return f"没准备：描述里有「{bad[0]}」，虚拟形象一律画成年人，这种画不了"
        no_pics = any(w in str(images or "") for w in ("不用", "不要", "没有", "无"))
        # 〈主人〉替 TA 准备：圖是〈主人〉這條帶的、引用的、剛在這裡發的；沒有就沿用 TA 之前那份的圖
        pics = [] if no_pics else await self.collect(event, str(event.get_sender_id() or "") if by_owner else me)
        saved = []
        for i, (u, w) in enumerate(pics):
            f = self.phone.pend_dir / f"{me}_{i}.jpg"
            if await self._save_pic(u, f):
                saved.append((f.name, ("〈主人〉" + w) if by_owner else w))
        if not saved and not no_pics and old.get("imgs"):
            kept = [f for f in old["imgs"] if (self.phone.pend_dir / f).exists()]
            saved = [(f, f"TA {_hm(old.get('ts'))} 自己给的那张") for f in kept]
            if kept and old.get("qq_ref"):
                saved = [(kept[0], "TA 的 QQ 头像")]
        qq_ref = bool(saved and old.get("qq_ref") and saved[0][1] == "TA 的 QQ 头像")
        if not saved and not no_pics and not qq_ref:  # 沒給圖：外觀照 TA 的 QQ 頭像（10-27 用戶定）
            f = self.phone.pend_dir / f"{me}_qq.jpg"
            if await self._save_pic(phone_mod.AVATAR_URL.format(qq=me), f):
                saved.append((f.name, "TA 的 QQ 头像"))
                qq_ref = True
        d = self.phone.avatars()
        name = (old.get("name") or me) if by_owner else (event.get_sender_name() or me)
        d.setdefault("pending", {})[me] = {"desc": desc, "imgs": [f for f, _ in saved], "qq_ref": qq_ref, "ts": int(time.time()),
                                          "mid": str(getattr(event.message_obj, "message_id", "") or ""),
                                          "name": name, **({"by": "owner"} if by_owner else {})}
        self.phone.save_avatars(d)
        got = ("、".join(w for _, w in saved) + ("（TA 没给图，外观照 QQ 头像，描述里写的照描述）" if qq_ref else "")
               if saved else "没有图（只照描述画）")
        lost = max(0, len(pics) - len(saved))
        if by_owner:
            return self.p.s.fill(
                f"记下了，还没画（〈主人〉请〈我〉给 QQ {me} 做的，用 TA 之前准备过的那份{'' if old else '——TA 没准备过，照这次写的'}）。"
                f"参考图 {len(saved)} 张：{got}" + (f"（另有 {lost} 张没下载下来）" if lost else "") + f"；描述：{desc}。"
                f"〈主人〉在之后的消息里确认了，再用「确认」（写上 qq）才画（同一条消息里不算，{PENDING_TTL // 60} 分钟内有效）；"
                "〈主人〉说了就算，不用 TA 再确认、不受每人一次的限制。画一张大概两三分钟，算进今天画图的张数")
        return self.p.s.fill(
            f"记下了，还没画{'（没写的照 TA 之前准备过的那份）' if old else ''}。参考图 {len(saved)} 张：{got}" + (f"（另有 {lost} 张没下载下来）" if lost else "")
            + f"；描述：{desc}。TA 本人在之后的消息里确认了，再用「确认」才画（同一条消息里不算，{PENDING_TTL // 60} 分钟内有效）；"
            "画一张大概一两分钟，算进今天画图的张数" + ("" if self.p.s.is_owner(me) else "，每人只能做一次"))

    async def _confirm(self, event, me: str, text: str, by_owner: bool = False, to_ta: bool = False) -> str:
        d = self.phone.avatars()
        pend = (d.get("pending") or {}).get(me)
        if not pend:
            return "没画：TA 还没有准备好的形象（先用「准备」）"
        if time.time() - pend.get("ts", 0) > PENDING_TTL:  # 不刪：〈主人〉替 TA 做時還能沿用這份
            return f"没画：准备的那份超过 {PENDING_TTL // 60} 分钟了，作废了，要重新准备"
        if bool(pend.get("by") == "owner") != by_owner:
            return self.p.s.fill("没画：这份是〈主人〉替 TA 准备的，要〈主人〉确认（写上 qq）" if pend.get("by") == "owner"
                                 else "没画：这份是 TA 自己准备的，要 TA 本人确认；〈主人〉要替 TA 做，先写上 qq 重新准备")
        mid = str(getattr(event.message_obj, "message_id", "") or "")
        if mid and mid == pend.get("mid"):
            return ("没画：要等〈主人〉在之后的消息里确认，准备的同一条消息里不算" if by_owner
                    else "没画：要等 TA 在之后的消息里确认，准备的同一条消息里不算")
        why = self._can_make(me, by_owner)
        if why:
            return f"没画：{why}"
        if me in self._busy:
            return "没画：TA 的形象正在画"
        self._busy.add(me)
        try:
            return await self._make(event, me, pend, text, to_ta=to_ta and by_owner)
        finally:
            self._busy.discard(me)

    def _style_refs(self) -> list[Path]:
        d = self.phone.av_dir / STYLE_DIR
        refs = sorted(f for f in d.glob("*") if f.suffix.lower() in STYLE_EXT) if d.is_dir() else []
        if not refs and self.p.self_ref and Path(self.p.self_ref).exists():
            refs = [Path(self.p.self_ref)]
        return refs

    async def _draw(self, prompt: str, refs: list, size: str) -> tuple[bytes | None, str]:
        last = "没有可用的画图配置"
        for p in self.p._drawing_providers():
            try:
                return await self.p._call_images(p, prompt, refs, size), ""
            except Exception as e:
                last = f"{p.get('model')}: {str(e) or type(e).__name__}"
        return None, last

    async def _make(self, event, me: str, pend: dict, text: str, to_ta: bool = False) -> str:
        """先在群漫畫裡畫一格 TA，再照那格畫三視圖（兩張都算進今天畫圖的張數）"""
        from .lively_common import ASK_OWNER
        took = self.p.take_draw()
        if not (took and self.p.take_draw()):  # 兩張一起先佔上，免得畫完那一格才發現張數不夠
            if took:
                self.p.give_back_draw()
            return self.p.s.fill(f"没画：今天画图的张数不够了：已经画了 {self.p.state['draw_count']} 张，一天最多 {self.p.draw_max} 张"
                                 "（聊天里画的、说说配图、定做形象一起算），定做一次要画两张；这一道〈主人〉叫的也算，张数〈主人〉在面板值班页能改" + ASK_OWNER)
        name = self.p._call_of(me, pend.get("name", ""))
        refs = [self.phone.pend_dir / f for f in pend.get("imgs") or []]
        refs = [f for f in refs if f.exists()]
        head = AVATAR_QQ_REF if pend.get("qq_ref") else AVATAR_REFS
        style = self._style_refs()
        k, n = len(refs) + 1, len(refs) + len(style)
        prompt = ((head.format(n=len(refs), name=name) if refs else "")
                  + (AVATAR_STYLE_REF.format(style_refs=f"Image {k} is" if k == n else f"Images {k} to {n} are") if style else "")
                  + AVATAR_PANEL_PROMPT.format(name=name, desc=pend["desc"]))
        from .main import draw_fail_reason
        panel, last = await self._draw(prompt, refs + style, "1024x1024")
        if panel is None:
            self.p.give_back_draw()
            self.p.give_back_draw()
            self.p._log("avatar_fail", qq=me, error=last[:300], step="panel")
            return f"没画成：{draw_fail_reason(last)}，不算次数，准备的那份还在"
        pf = self.phone.av_dir / f"{me}_panel.png"
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_bytes(panel)
        data, last = await self._draw(AVATAR_PROMPT.format(name=name), [pf], "1536x1024")
        if data is None:
            self.p.give_back_draw()
            self.p._log("avatar_fail", qq=me, error=last[:300], step="sheet")
            return f"没画成：漫画里那一格画好了，照它画三视图时{draw_fail_reason(last)}，不算次数，准备的那份还在"
        f = self.phone.av_dir / f"{me}.png"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        try:
            self.p.gallery.add(str(f), "形象", qq=me, chat="定做形象", purpose="定做形象的三视图")
        except Exception:
            pass
        d = self.phone.avatars()
        old = (d.get("made") or {}).get(me) or {}
        d.setdefault("made", {})[me] = {"file": f.name, "desc": pend["desc"], "imgs": len(refs), "ts": int(time.time()),
                                        "count": int(old.get("count") or 0) + 1, "name": pend.get("name", ""),
                                        "panel": pf.name, **({"by": "owner"} if pend.get("by") == "owner" else {})}
        (d.get("pending") or {}).pop(me, None)
        (d.get("allow") or {}).pop(me, None)
        self.phone.save_avatars(d)
        self.p._log("avatar", qq=me, desc=pend["desc"][:200], imgs=len(refs), **({"by": "owner"} if pend.get("by") == "owner" else {}))
        self.p._seen[event.unified_msg_origin] = str(f)  # 工具回傳時帶這張三視圖給她看
        sent = "，发到这里了"
        try:  # 大圖先轉 JPEG；QQ 報超時就翻那邊的消息核對（10-29 10:33 fuyu 那張報超時、其實發到了，被當成發不出去）
            await self.p._send_checked(event.unified_msg_origin, str(f), str(text or "").strip()[:200])
        except Exception as e:
            logger.warning(f"[lively_comic] 定做的形象发不出去：{e}")
            sent = "，但是发不出去（图存下了）"
        if pend.get("by") == "owner":
            sent += await self._send_ta(me, f, text) if to_ta else "；TA 那边还没收到"
        task = asyncio.create_task(self._make_card(me, name, f, d["made"][me]["ts"]))
        self.p._bg.add(task)
        task.add_done_callback(self.p._bg.discard)
        return (f"画好了，TA 的虚拟形象存下了{sent}；以后群漫画、别的图画到 TA 就照这张。"
                "印象卡上也会换成 TA 的形象：照这张再画一张半身像当卡面，正在画（不用 TA 再确认，也算一张）")

    async def _send_ta(self, qq: str, f, text: str) -> str:
        """〈主人〉替 TA 做的，也發到 TA 的私聊（要是 QQ 好友）"""
        client = self.p.s.client()
        try:
            rows = await client.api.call_action("get_friend_list") if client else []
        except Exception:
            rows = []
        if qq not in {str(r.get("user_id")) for r in rows or []}:
            return "；TA 不是〈我〉的 QQ 好友，私聊发不过去"
        try:
            await self.p._send_checked(self.p.s.private_umo(qq), str(f), str(text or "").strip()[:200])
            return "；也发到 TA 的私聊了（带的话一样）"
        except Exception as e:
            logger.warning(f"[lively_comic] 定做的形象发到 TA 私聊没成：{e}")
            return "；发到 TA 私聊时出错了，TA 那边没收到"

    def duo_dir(self) -> Path:
        from .lively_common import PLUGIN_DATA
        return PLUGIN_DATA / "astrbot_plugin_lively_bond" / "card_bg"

    def duo_has_bg(self, qq: str) -> bool:
        d = self.duo_dir()
        return any((d / f"{qq}{e}").exists() for e in (".webp", ".png", ".jpg", ".jpeg"))

    async def make_duo(self, qq: str, name: str) -> tuple[Path | None, str]:
        """畫 TA 的虛擬形象（沒定做的照 QQ 頭像）和〈我〉的合照，換成 TA 印象卡的專屬背景。
        返回 (純背景圖 jpg（發給 TA 用）, 沒畫成的原因)。算一張畫圖張數"""
        from .lively_common import ASK_OWNER
        me_ref = self.p.me_ref()
        if not me_ref:
            return None, "找不到〈我〉自己的参考图"
        made = self.phone.made(qq) or {}
        sheet = self.phone.av_dir / str(made.get("file") or "")
        if made.get("file") and sheet.is_file():
            ref, how = sheet, DUO_HOW_MADE
        else:
            ref = self.phone.pend_dir / f"{qq}_duo_qq.jpg"
            if not await self._save_pic(phone_mod.AVATAR_URL.format(qq=qq), ref):
                return None, "TA 的 QQ 头像没下载下来"
            how = DUO_HOW_QQ
        if not self.p.take_draw():
            return None, f"今天画图的张数用完了（一天最多 {self.p.draw_max} 张，聊天里画的、说说配图、定做形象一起算）" + ASK_OWNER
        call = self.p._call_of(qq, name)
        prompt = (DUO_WHO.format(name=call, how=how, name_short=f"「{call}」") + DUO_SCENE.format(name=call) + DUO_STYLE)
        data, last = await self._draw(prompt, [me_ref, ref], "1024x1536")
        if data is None:
            self.p.give_back_draw()
            from .main import draw_fail_reason
            self.p._log("duo_fail", qq=qq, error=last[:300])
            return None, draw_fail_reason(last)
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB").resize((900, 1350), Image.LANCZOS)
        d = self.duo_dir()
        d.mkdir(parents=True, exist_ok=True)
        for e in (".png", ".jpg", ".jpeg"):  # 同一個人只留一張，bond 按檔名認
            (d / f"{qq}{e}").unlink(missing_ok=True)
        im.save(d / f"{qq}.webp", "WEBP", quality=90)
        (d / f"{qq}.txt").write_text(DUO_LOOK + "\n", "utf-8")
        out = self.phone.av_dir / f"{qq}_duo.jpg"
        im.save(out, "JPEG", quality=92)
        self.p._log("duo", qq=qq, made=how == DUO_HOW_MADE)
        return out, ""

    async def _make_card(self, me: str, name: str, sheet, ts: int) -> None:
        """照三視圖畫印象卡的卡面圖；沒畫成就算了（bond 畫卡時從三視圖裁）"""
        if not self.p.take_draw():
            self.p._log("avatar_card_fail", qq=me, error="今天画图的张数用完了")
            return
        data, last = await self._draw(AVATAR_CARD_PROMPT.format(name=name), [sheet], "1536x1024")
        if data is None:
            self.p.give_back_draw()
            self.p._log("avatar_card_fail", qq=me, error=last[:300])
            return
        f = self.phone.av_dir / f"{me}_card.png"
        f.write_bytes(data)
        d = self.phone.avatars()
        rec = (d.get("made") or {}).get(me)
        if not rec or rec.get("ts") != ts:  # 畫的這幾十秒裡形象又重做了，這張不算
            return
        rec["card"] = f.name
        self.phone.save_avatars(d)
        self.p._log("avatar_card", qq=me)

    def _look(self, qq: str) -> str:
        rec = self.phone.made(qq)
        if not rec:
            return f"QQ {qq} 没有定做的形象，画到 TA 时照 TA 的 QQ 头像画"
        if rec.get("preset"):
            return self.p.s.fill("这是〈主人〉，用的是素材里〈主人〉的样子")
        n, allowed = self._times(qq)
        if rec.get("source") == "qq" and not n:
            return (f"QQ {qq} 有照 TA 的 QQ 头像先做的形象（{_hm(rec.get('ts'))} 做的，TA 自己还没定做过，想要可以定做一次）："
                    f"{rec.get('desc', '')}")
        return (f"QQ {qq} 有定做的形象（{_hm(rec.get('ts'))} 做的，用了 {rec.get('imgs', 0)} 张参考图）：{rec.get('desc', '')}"
                + ("；〈主人〉放行过，可以再做一次" if allowed else ""))

    async def _look_group(self, target: str) -> str:
        """某個群裡誰有形象（10-30：她要挑小凛群有形象的人，只能一個個 QQ 問，漏了布丁）。
        群成員名單問 NapCat，跟形象記錄對一遍；照 QQ 頭像先做的另列"""
        gid, why = self.p._find_group(target)
        if not gid:
            return why
        client = self.p.s.client()
        if client is None:
            return "QQ 这会儿连不上，拿不到群成员，这次没查成"
        try:
            members = await client.api.call_action("get_group_member_list", group_id=int(gid))
        except Exception as e:
            return f"拿不到群成员（{type(e).__name__}），这次没查成"
        own, from_qq = [], []
        for m in members or []:
            qq = str((m or {}).get("user_id") or "")
            rec = self.phone.made(qq) if qq else None
            if not rec:
                continue
            name = str(m.get("card") or m.get("nickname") or qq)
            if rec.get("preset"):
                own.append(self.p.s.fill(f"{name}（{qq}，〈主人〉，用素材里〈主人〉的样子）"))
            elif rec.get("source") == "qq" and not self._times(qq)[0]:
                from_qq.append(f"{name}（{qq}）")
            else:
                own.append(f"{name}（{qq}）")
        head = f"群「{self.p._gname(gid)}」（{gid}）{len(members or [])} 个人里"
        if not own and not from_qq:
            return head + "没有人有形象，画到谁都照 TA 的 QQ 头像画"
        out = [head + "有形象的："]
        if own:
            out.append("· 定做的：" + "、".join(own))
        if from_qq:
            out.append("· 照 QQ 头像先做的（TA 自己还没定做）：" + "、".join(from_qq))
        out.append("其余的人没有形象，画到 TA 时照 QQ 头像画；谁的形象长什么样，用「看」写 qq 查")
        return "\n".join(out)

    def _allow(self, me: str, qq: str) -> str:
        if not self.p.s.is_owner(me):
            return self.p.s.fill("没放行：只有〈主人〉说了才算")
        qq = re.sub(r"\D", "", str(qq or ""))
        if not qq:
            return "没放行：要写放行谁（QQ 号）"
        d = self.phone.avatars()
        d.setdefault("allow", {})[qq] = int(time.time())
        self.phone.save_avatars(d)
        return self.p.s.fill(f"放行了：QQ {qq} 可以再做一次虚拟形象（TA 再准备、确认就会画；〈主人〉这边也可以写 qq 直接替 TA 准备、确认）")
