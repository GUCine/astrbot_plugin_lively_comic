"""圖冊（11-02）：每張畫好的圖有一個編號、記著它是什麼、在哪畫的、發過哪裡。
起因：11-02 00:17 她要補發「纯良群下午画的群漫画」，lively_comic_post 沒法指定是哪一張，默認發了「最近畫的」——一張說說配圖的自拍。
現在發圖一定要寫編號（lively_comic_post 的 image），程式按圖冊記的種類、地點檢查，擋住時說清楚是哪一道。

正本 gallery.json 在後台（她改不到）；她看得到的一份 图册.txt 每次變動重寫（一行一張、新的在上），放在她電腦「素材」資料夾，
她改了那份不影響正本。編號全局遞增、不重用；超過 30 天的搬到 gallery-old.jsonl，編號照樣查得到。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
KEEP_DAYS = 30
ID_RE = re.compile(r"^\s*(?:[#＃]|图|圖)?\s*(\d{1,9})\s*$")
SINGLE_KINDS = ("群漫画单张", "修图")  # 群漫畫只能整頁發，這兩種不單發
LIST_SKIP = ("形象",)  # 列給她挑的時候不列


class Gallery:
    def __init__(self, folder: Path, root: Path | None = None, group_name=None):
        """folder：後台資料目錄（放 gallery.json）；root：她電腦「素材」資料夾在容器裡的位置（放 图册.txt、算相對路徑），沒有就不寫；
        group_name：群號 → 群名"""
        self.file = Path(folder) / "gallery.json"
        self.old = Path(folder) / "gallery-old.jsonl"
        self.root = Path(root) if root else None
        self.group_name = group_name or (lambda gid: str(gid))
        self.data = {"seq": 0, "items": {}}
        try:
            d = json.loads(self.file.read_text("utf-8"))
            if isinstance(d, dict) and isinstance(d.get("items"), dict):
                self.data = {"seq": int(d.get("seq") or 0), "items": d["items"]}
        except (OSError, ValueError):
            pass

    # ---------- 存取 ----------
    def _save(self):
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), "utf-8")
        tmp.replace(self.file)

    def _rel(self, path: str) -> str:
        """素材資料夾底下的相對路徑，用反斜線（她電腦那邊的寫法）；不在素材底下就只留檔名"""
        try:
            if self.root:
                return str(Path(path).resolve().relative_to(self.root.resolve())).replace("/", "\\")
        except (ValueError, OSError):
            pass
        return Path(path).name

    def add(self, path: str, kind: str, **meta) -> int:
        """登記一張，回編號。meta：where（在哪個聊天畫的 umo）、purpose、prompt、shot／look／shape／refs、group／day／k／n／title、parent、status"""
        now = time.time()
        self.data["seq"] += 1
        n = self.data["seq"]
        item = {"id": n, "ts": int(meta.pop("ts", now)), "kind": kind, "path": str(path), "file": self._rel(str(path)),
                "status": meta.pop("status", "画好"), "sent": []}
        if "prompt" in meta:
            meta["prompt"] = str(meta["prompt"] or "")[:300]
        item.update({k: v for k, v in meta.items() if v not in (None, "", [])})
        self.data["items"][str(n)] = item
        self._archive(now)
        self._save()
        self.render()
        return n

    def _archive(self, now: float):
        cut = now - KEEP_DAYS * 86400
        old = [k for k, v in self.data["items"].items() if v.get("ts", 0) < cut]
        if not old:
            return
        try:
            with self.old.open("a", encoding="utf-8") as f:
                for k in old:
                    f.write(json.dumps(self.data["items"][k], ensure_ascii=False) + "\n")
        except OSError:
            return
        for k in old:
            self.data["items"].pop(k, None)

    def get(self, n) -> dict | None:
        n = str(n)
        got = self.data["items"].get(n)
        if got:
            return got
        try:
            for line in self.old.read_text("utf-8").splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if str(d.get("id")) == n:
                    return d
        except OSError:
            pass
        return None

    @staticmethod
    def parse_id(s) -> int | None:
        """「#123」「图123」「123」都認；別的寫法回 None"""
        m = ID_RE.match(str(s or ""))
        return int(m.group(1)) if m else None

    def update(self, n: int, **kv):
        it = self.data["items"].get(str(n))
        if it is None:
            return
        it.update(kv)
        self._save()
        self.render()

    def set_status(self, n: int, status: str):
        self.update(n, status=status)

    def mark_sent(self, n: int, to: str, ts: float | None = None, late: bool = False, show: bool = False, umo: str = ""):
        """記發到哪了。show：只是拿給這裡的人看（lively_pic），不算發群、不改狀態"""
        it = self.data["items"].get(str(n))
        if it is None:
            return
        rec = {"to": to, "ts": int(ts or time.time()), **({"umo": umo} if umo else {}), **({"late": True} if late else {}),
               **({"show": True} if show else {})}
        it.setdefault("sent", []).append(rec)
        if not show:
            it["status"] = "已发"
        self._save()
        self.render()

    def add_where(self, n: int, umo: str):
        """群裡叫她畫、發到私聊的：在叫她畫的那個聊天裡也算「刚画的」"""
        it = self.data["items"].get(str(n))
        if it is not None and umo and umo != it.get("where") and umo not in it.setdefault("also", []):
            it["also"].append(umo)
            self._save()

    def recent(self, where: str | None = None, kind=None, limit: int = 8, group: str | None = None,
               within: float | None = None, day: str | None = None, skip=LIST_SKIP) -> list[dict]:
        """最近的在前。where：在這個聊天畫的（也包括 also）；kind：一個或幾個種類；group：群漫畫的群；within：幾秒以內；day：群漫畫的那一天"""
        kinds = {kind} if isinstance(kind, str) else set(kind or ())
        now = time.time()
        out = []
        for it in sorted(self.data["items"].values(), key=lambda x: -x.get("id", 0)):
            if skip and it.get("kind") in skip and not kinds:
                continue
            if kinds and it.get("kind") not in kinds:
                continue
            if where is not None and where != it.get("where") and where not in (it.get("also") or []):
                continue
            if group is not None and str(it.get("group")) != str(group):
                continue
            if day is not None and it.get("day") != day:
                continue
            if within is not None and now - it.get("ts", 0) > within:
                continue
            out.append(it)
            if len(out) >= limit:
                break
        return out

    def find_path(self, path: str, kind=None) -> dict | None:
        """按檔案路徑找（最新的一筆）；kind 可以限定種類"""
        kinds = {kind} if isinstance(kind, str) else set(kind or ())
        for it in sorted(self.data["items"].values(), key=lambda x: -x.get("id", 0)):
            if it.get("path") == str(path) and (not kinds or it.get("kind") in kinds):
                return it
        return None

    def page_of(self, n: int) -> dict | None:
        """這一張（單張、修圖）所在的那一組的整頁；沒有回 None。整頁自己回自己"""
        it = self.get(n)
        seen = set()
        while it and it.get("id") not in seen:
            seen.add(it.get("id"))
            if it.get("kind") == "群漫画整页":
                return it
            for cand in sorted(self.data["items"].values(), key=lambda x: -x.get("id", 0)):
                if cand.get("kind") == "群漫画整页" and it.get("id") in (cand.get("parent") or []):
                    return cand
            par = it.get("parent")
            it = self.get(par if not isinstance(par, list) else (par[0] if par else 0)) if par else None
        return None

    # ---------- 文字 ----------
    @staticmethod
    def _hm(ts) -> str:
        return datetime.fromtimestamp(ts, TZ).strftime("%H:%M")

    @staticmethod
    def _md(ts) -> str:
        return datetime.fromtimestamp(ts, TZ).strftime("%m-%d")

    def line(self, n) -> str:
        """一行說明：#131 群漫画整页｜「我们是纯良…」11-01｜3 张｜22:53 画好｜22:54 发到那个群了"""
        it = n if isinstance(n, dict) else self.get(n)
        if not it:
            return f"#{n} 图册里没有"
        kind = it.get("kind", "")
        parts = [f"#{it['id']} {kind}" + (f"·{it['shot']}" if kind == "拍照" and it.get("shot") else "")]
        if it.get("group"):
            gname = self.group_name(it["group"])
            day = it.get("day") or ""
            parts.append(f"「{gname}」{day[5:] if len(day) >= 10 else day}".strip())
        if kind == "群漫画整页":
            parts.append(f"{it['n']} 张" if it.get("n") else "")
        elif kind == "群漫画单张" and it.get("k"):
            parts.append(f"第 {it['k']}/{it.get('n') or '?'} 张" + (f"「{it['title']}」" if it.get("title") else ""))
        elif kind in ("拍照", "说说配图", "修图"):
            parts.append(f"{self._md(it['ts'])} {self._hm(it['ts'])}")
        if it.get("chat"):  # 在哪個聊天畫的（登記時寫好的一句話，例如「〈主人〉私聊」「别人的私聊」）
            parts.append(it["chat"])
        if it.get("purpose"):
            parts.append(f"用途：{it['purpose']}")
        parts.append(f"{self._hm(it['ts'])} 画好")
        real = [s for s in it.get("sent") or [] if not s.get("show")]
        shown = [s for s in it.get("sent") or [] if s.get("show")]
        if real:
            parts.append("；".join(f"{self._hm(s['ts'])} 发到{s['to']}" + ("（QQ 报超时，其实到了）" if s.get("late") else "") for s in real[-2:]))
        elif it.get("status") and it["status"] != "画好":
            parts.append(it["status"] + (f"（{it['failed']}）" if it.get("failed") else ""))
        else:
            parts.append("还没发过")
        if shown:
            parts.append("拿给" + "、".join(sorted({s["to"] for s in shown})) + "看过")
        return "｜".join(p for p in parts if p)

    def render(self):
        """重寫她看得到的 图册.txt（新的在上）"""
        if self.root is None:
            return
        try:
            rows = sorted(self.data["items"].values(), key=lambda x: -x.get("id", 0))
            head = ("# 图册：每张画好的图一个编号（发图时写编号）。这份只是给你看的，改了不会影响真正的记录。\n"
                    "# 编号｜种类｜在哪画的、哪天｜用途｜画好时间｜发过哪里｜文件\n")
            body = "\n".join(self.line(r) + f"｜文件：{r.get('file', '')}" for r in rows)
            (self.root / "图册.txt").write_text(head + body + "\n", "utf-8")
        except OSError:
            pass
