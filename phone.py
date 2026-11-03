"""手機拍照（10-27）：lively_draw 她理解成用自己的手機拍照、截屏，底下照樣是生圖模型。

- 拍法（shot）、畫風（look）、形狀（shape）、帶哪些參考素材（refs）都是她選，程式只把她選的翻成英文構圖說明、帶上對應的參考圖
- 參考素材在資料目錄 refs/（refs.json 一張一行：name 她寫的名字、desc 給她看、en 給畫圖模型，real/real_en 是 look=真人 時換用的照片）
- 畫到群友：refs 裡寫 TA 的 QQ 號，定做過形象（avatars/）就用那張，沒有就拿 TA 的 QQ 頭像當參考圖，提示詞讓模型照頭像做成同一畫風的人；
  頭像不是人（風景、寵物、logo）也照它的顏色和主題設計一個人，不另外先分類
- 一張最多帶 MAX_REFS 張參考圖（中轉站的選圖頁只放到 10 張）
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

TZ = timezone(timedelta(hours=8))
MAX_REFS = 10
AVATAR_URL = "https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640"


def jpeg_bytes(data: bytes) -> bytes | None:
    """QQ 給的頭像不一定是 JPEG（有人是 GIF、帶透明的 PNG），照原樣存成 .jpg 送去畫圖，
    中轉站會當成壞圖整張拒掉（10-27 某個群「参考图损坏或无效」）。一律轉成真的 JPEG（動圖取第一幀，
    透明的鋪白底）；讀不出來是 None，那個人就不帶頭像"""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.seek(0)
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        buf = io.BytesIO()
        bg.save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return None
AVATAR_TTL = 3 * 86400  # QQ 頭像快取多久（換了頭像過幾天才跟上）
SHAPES = {"方": "1024x1024", "直": "1024x1536", "竖": "1024x1536", "横": "1536x1024"}
SHOTS = {
    "自拍": ("This is a selfie Xiaofeiyu took of herself with her own phone: held at arm's length or taken in a mirror, "
             "natural phone-camera framing and perspective. She does not have to look at the camera; a candid moment is fine."),
    "随手拍": ("This is a casual photo Xiaofeiyu snapped with her own phone from her own point of view (first person): she is behind "
               "the camera, so she is not in the picture, except maybe her own hand, legs, feet or tail at the edge of the frame, "
               "seen from her own eyes."),
    "截图": ("This is a screenshot of Xiaofeiyu's iPhone screen: exactly what the screen shows, full frame, iOS interface "
             "(status bar at the top with the time {hhmm}, signal and battery). No phone body, no hands, not a photo of a screen."),
}
SHOT_ALIAS = {"自拍照": "自拍", "镜子": "自拍", "随拍": "随手拍", "拍照": "随手拍", "截屏": "截图", "屏幕": "截图"}
LOOKS = {
    "二次元": "Art style: anime illustration in the same style as the reference character art (soft colors, clean lines).",
    "真人": ("Photorealistic, like a real photo taken with an iPhone: real people and real places, natural light, real skin and "
             "fabric textures; Xiaofeiyu is a real adult woman cosplaying her (blue wavy wig, whale-fin ear props, plush whale tail "
             "prop). Not anime, not a drawing."),
}
LOOK_ALIAS = {"真人cos": "真人", "cos": "真人", "现实": "真人", "照片": "真人", "动漫": "二次元", "插画": "二次元"}
# 有參考圖的人長相只照圖（10-29 用戶定：有虛擬形象就不在提示詞裡描述長相，免得畫錯；她寫了也不用）
LOOK_FROM_REF = ("Every person who has a reference image above gets their looks (hair, eyes, face, clothes, accessories) "
                 "only from that image; ignore any description of their looks in the text below.")
TAIL = ("Everyone in the picture is an adult. Do not add captions, labels, names or watermarks unless the description asks for "
        "text (the phone's own interface text in a screenshot is fine).")
PERSON_EN = ("the QQ avatar of the person 「{call}」: draw {call} as a young adult character based on this avatar (hair, colors, "
             "outfit, vibe) in the same style as the rest of the picture; if the avatar is not a person (scenery, pet, logo, text), "
             "design a young adult character inspired by its colors and subject")
# 群漫畫：QQ 頭像裡有沒有能照著畫的人（10-31 爱丽丝的頭像是黑白風景，畫圖模型照不出人，套了旁邊张顺平的樣子）。
# 每張頭像問一次看圖模型，記在 avatars_meta/qq_face.json（頭像換了才再問）；定做過形象的人不問
FACE_ASK = ("这是一个 QQ 头像。里面有没有一个能照着画出长相的人物？真人、动漫或游戏角色都算，只要看得清脸、发型和穿着；"
            "风景、动物、物品、标志、文字、看不清脸的远景小人都不算。只输出 JSON：{\"人物\": true 或 false}")
PERSON_MADE_EN = "the character sheet of the person 「{call}」: draw {call} exactly like this character"


def norm(word: str, table: dict, alias: dict) -> str:
    w = re.sub(r"\s", "", str(word or "")).lower()
    if not w:
        return ""
    for k in table:
        if k in w:
            return k
    for k, v in alias.items():
        if k in w:
            return v
    return ""


class Phone:
    def __init__(self, plugin):
        self.p = plugin
        self._items: list[dict] = []
        self._mtime = -1.0

    @property
    def refs_dir(self) -> Path:
        return self.p.dir / "refs"

    @property
    def av_dir(self) -> Path:
        """形象的圖（三視圖、卡面、畫風參考）：10-29 起是她電腦上的「素材\\形象」（這個目錄是指過去的連結）"""
        return self.p.dir / "avatars"

    @property
    def meta_dir(self) -> Path:
        """形象的記錄 avatars.json、QQ 頭像快取、還沒確認的參考圖：留在後台，不放電腦"""
        return self.p.dir / "avatars_meta"

    @property
    def refs_json(self) -> Path:
        """拍照素材的清單：留在後台（圖在 refs/，是電腦上的「素材\\拍照素材」）"""
        f = self.p.dir / "refs.json"
        return f if f.exists() or not (self.refs_dir / "refs.json").exists() else self.refs_dir / "refs.json"

    # ---------- 參考素材 ----------
    def items(self) -> list[dict]:
        f = self.refs_json
        try:
            m = f.stat().st_mtime
        except OSError:
            self._items, self._mtime = [], -1.0
            return []
        if m != self._mtime:
            try:
                d = json.loads(f.read_text(encoding="utf-8-sig"))
                self._items = [x for x in d.get("items") or [] if isinstance(x, dict) and x.get("name") and x.get("file")]
            except Exception:
                self._items = []
            self._mtime = m
        return self._items

    def listing(self) -> str:
        """工具說明後面接的素材清單：「名字：說明」一行一個"""
        rows = [f"- {self.p.s.fill(x['name'])}：{self.p.s.fill(x.get('desc') or '')}" for x in self.items()
                if (self.refs_dir / x["file"]).exists()]
        return "\n".join(rows)

    def _item(self, name: str) -> dict | None:
        name = name.strip()
        for x in self.items():
            if name in (x["name"], self.p.s.fill(x["name"])):
                return x
        return None

    def _file(self, name: str) -> Path | None:
        f = self.refs_dir / name
        return f if name and f.exists() else None

    # ---------- 人 ----------
    def avatars(self) -> dict:
        for f in (self.meta_dir / "avatars.json", self.av_dir / "avatars.json"):  # 後一個是搬之前的位置
            if f.exists():
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    return {}
        return {}

    def save_avatars(self, d: dict):
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.meta_dir / "avatars.json.tmp"
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.meta_dir / "avatars.json")

    @property
    def pend_dir(self) -> Path:
        return self.meta_dir / "pending"

    def made(self, qq: str) -> dict | None:
        """定做過的形象 {"file", "desc", "ts", "count"}（圖還在的）；主人用素材裡〈主人〉那張"""
        rec = (self.avatars().get("made") or {}).get(str(qq))
        if rec and (self.av_dir / rec.get("file", "")).exists():
            return rec
        if self.p.s.is_owner(qq):
            x = self._item("〈主人〉")
            if x and self._file(x["file"]):
                return {"file": str(self._file(x["file"])), "desc": x.get("desc", ""), "preset": True}
        return None

    async def person(self, qq: str, call: str = "") -> tuple[Path, str] | None:
        """畫到這個人用哪張參考圖：定做的形象 → QQ 頭像（快取幾天）；拿不到就 None"""
        qq = str(qq)
        call = call or qq
        rec = self.made(qq)
        if rec:
            f = Path(rec["file"]) if Path(rec["file"]).is_absolute() else self.av_dir / rec["file"]
            if self.p.s.is_owner(qq):
                x = self._item("〈主人〉")
                return f, (x.get("en") if x else PERSON_MADE_EN.format(call=call))
            return f, PERSON_MADE_EN.format(call=call)
        f = self.meta_dir / "qq" / f"{qq}.jpg"
        if f.exists() and f.read_bytes()[:2] != b"\xff\xd8":  # 以前照原樣存的（GIF、PNG 也叫 .jpg）：轉一次，轉不了就刪掉重拿
            data = jpeg_bytes(f.read_bytes())
            f.write_bytes(data) if data else f.unlink()
        if not f.exists() or time.time() - f.stat().st_mtime > AVATAR_TTL:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                    async with s.get(AVATAR_URL.format(qq=qq)) as r:
                        data = await r.read() if r.status == 200 else b""
                data = jpeg_bytes(data) if len(data) > 500 else None
                if data:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
            except Exception:
                pass
        return (f, PERSON_EN.format(call=call)) if f.exists() else None

    async def has_face(self, qq: str) -> bool | None:
        """群漫畫用：這個人的 QQ 頭像能不能當參考圖畫出 TA。定做過形象的、問不到的回 None（照舊帶）"""
        qq = str(qq)
        if self.made(qq):
            return None
        got = await self.person(qq)
        if not got:
            return None
        import hashlib
        f = got[0]
        md5 = hashlib.md5(f.read_bytes()).hexdigest()
        cache_f = self.meta_dir / "qq_face.json"
        try:
            cache = json.loads(cache_f.read_text(encoding="utf-8")) if cache_f.exists() else {}
        except Exception:
            cache = {}
        rec = cache.get(qq) or {}
        if rec.get("md5") == md5 and isinstance(rec.get("face"), bool):
            return rec["face"]
        s = self.p.s
        prov = s.provider("look_provider_id" if s.get("look_provider_id") else "storyboard_provider_id")
        if prov is None:
            return None
        out = ""
        try:
            resp = await asyncio.wait_for(prov.text_chat(prompt=FACE_ASK, image_urls=[str(f)]), timeout=90)
            out = getattr(resp, "completion_text", "") or ""
            m = re.search(r"\{.*\}", out, re.S)
            face = json.loads(m.group(0)).get("人物") if m else None
        except Exception as e:
            out = f"{type(e).__name__}: {e}"
            face = None
        if isinstance(face, str) and face.strip().lower() in ("true", "false"):
            face = face.strip().lower() == "true"
        if not isinstance(face, bool):
            from astrbot.api import logger
            logger.warning(f"[lively_comic] {qq} 的头像是不是人没看成，照旧带头像：{out[:150]}")
            return None
        cache[qq] = {"md5": md5, "face": face, "ts": int(time.time())}
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_f.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(cache_f)
        return face

    # ---------- 拼起來 ----------
    async def build(self, prompt: str, shot: str = "", look: str = "", shape: str = "", refs: str = "",
                    with_self: bool = False, call_of=None, qq_of=None) -> dict:
        """她選的 → {"prompt": 給畫圖模型的英文, "refs": [Path], "size", "shot", "look", "used": [名字], "missing": [沒找到的]}"""
        shot = norm(shot, SHOTS, SHOT_ALIAS)
        look = norm(look, LOOKS, LOOK_ALIAS) or "二次元"
        size = SHAPES.get(norm(shape, SHAPES, {"square": "方", "portrait": "直", "landscape": "横", "长": "直", "宽": "横"}),
                          SHAPES["方"])
        names = [n for n in re.split(r"[,，、;；\s]+", str(refs or "")) if n]
        outfit = {"家居服", "睡衣"}
        if (with_self or shot == "自拍") and "我" not in names and not outfit & set(names):
            names.insert(0, "我")  # 自拍一定有她自己
        pics: list[tuple[Path, str]] = []
        used, missing, people = [], [], []
        seen: set[str] = set()

        def add(f: Path | None, en: str):
            if f and str(f) not in seen and len(pics) < MAX_REFS:
                seen.add(str(f))
                pics.append((f, en))

        owner = str(getattr(self.p.s, "owner", lambda: "")() or "")
        for n in names:
            x = self._item(n)
            if x and self.p.s.fill(x["name"]) == self.p.s.fill("〈主人〉") and owner and self.made(owner):
                n = owner  # 〈主人〉有定做的形象：照形象畫，不用素材裡那張
            elif not x and qq_of and not re.fullmatch(r"\d{5,}", n.strip()):
                n = qq_of(n) or n  # 寫的是名字、她叫 TA 的、群名片：認成 QQ
            qq = re.sub(r"\D", "", n)
            if qq and len(qq) >= 5 and qq == n.strip():
                got = await self.person(qq, call_of(qq) if call_of else qq)
                if got:
                    add(*got)
                    used.append(n)
                    people.append({"qq": qq, "call": call_of(qq) if call_of else qq, "made": self.made(qq)})
                else:
                    missing.append(n)
                continue
            x = self._item(n)
            if not x or not self._file(x["file"]):
                missing.append(n)
                continue
            used.append(self.p.s.fill(x["name"]))
            real = look == "真人" and self._file(x.get("real", ""))
            if real:
                if x.get("real_keep"):
                    add(self._file(x["file"]), x.get("en", ""))
                add(real, x.get("real_en") or x.get("en", ""))
            else:
                add(self._file(x["file"]), x.get("en", ""))
        lines = []
        if pics:
            lines.append("Reference images, in order:")
            lines += [f"Image {i}: {en}." for i, (_, en) in enumerate(pics, 1)]
            if people or "我" in used or self.p.s.fill("〈我〉") in used:
                lines.append(LOOK_FROM_REF)
        if shot:
            lines.append(SHOTS[shot].format(hhmm=datetime.now(TZ).strftime("%H:%M")))
        if shot != "截图" or look == "真人":
            lines.append(LOOKS[look])
        lines.append("What the picture shows: " + str(prompt or "").strip())
        lines.append(TAIL)
        return {"prompt": "\n".join(lines), "refs": [f for f, _ in pics], "size": size, "shot": shot or "其他",
                "look": look, "used": used, "missing": missing, "people": people}
