"""每日群漫畫：先私信主人預覽，主人說「發群」才發到群裡。

畫漫畫用的是「群分析總結」插件（SXP-Simon/astrbot_plugin_qq_group_daily_analysis）的內部服務，
本插件只負責：定時、先審後發、擋住它會直接往群裡髮長圖的 LLM 工具。
那個插件自己的定時分析、自動漫畫都關著，所以它不會自己往群裡發東西。

主人（只有主人）在群聊或私聊裡讓機器人畫畫：模型呼叫 lively_draw，後台畫好直接發到當前會話
（別人發消息時這個工具對模型不可見；每天最多 draw_daily_max 張）

主人私信指令：
- 發群（發群裡吧、這張發群…）：把最新給主人看的那張發到群裡。群漫畫發回它自己的群；
  剛畫的圖開了幾個群就要說發哪個：「發群 群號」或「發群 全部」（只開了一個群就直接發）
- 漫畫發群：只發待審的群漫畫；漫畫不發 [群號]：丟掉；漫畫重畫 [群號]：按同一天再畫一張（幾個群都在等時可以帶群號）
- 群漫畫 現在/今天/昨天/前天：馬上畫那一天的（預覽）；群漫畫 開 / 關 / 狀態
- 群漫畫 開 群號 / 群漫畫 關 群號：單獨開關某個群（服務的群預設都開）
- 群漫畫 自動發 / 審核：每天定時畫的直接發群還是先給主人看（預設直接發）
主人用自然語言說「把昨天的群聊畫成漫畫」「發群裡」時，模型呼叫 lively_group_comic / lively_comic_post
"""
import asyncio
import base64
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api import AstrBotConfig
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.agent.message import TextPart
from astrbot.core.message.message_event_result import MessageChain

from .lively_common import CONFIG_DIR, DATA, Settings, T2S, id_list

PENDING_TTL = 36 * 3600
GDA = "astrbot_plugin_qq_group_daily_analysis"
BLOCKED_TOOLS = ("group_daily_analysis_trigger",)  # 會直接髮長圖到群裡，跳過主人審核
TZ = timezone(timedelta(hours=8))
GDA_CONFIG = CONFIG_DIR / f"{GDA}_config.json"
FETCH_MAX = 4000  # 一天能有一千多條，拉夠整天再均勻抽樣
DRAW_POST_TTL = 2 * 3600  # 剛畫的圖多久內還能「發群」
DAY_WORDS = {"": 0, "现在": 0, "今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}
SEND_RE = re.compile(
    r"^(?:好|行|嗯|可以|那就|就)?[，,\s]*(?:把|将)?(?:这张|这个|它|那张|刚才那张|刚刚那张|刚画的|这张图|漫画|图)?"
    r"(?:发|发到|发去|发进|丢到|丢进|转到|转发到)(?:群|群里|群里面)(?:吧|啦|呀|啊|去|去吧|～|~|!|！|。)*$"
)
SEND_TO_RE = re.compile(r"^(?:把.{0,6})?发(?:到)?群\s*(\d{5,12}|全部|所有|都发)$")
HISTORY_USER_TEXT = "（系统记录：群漫画插件做的事，不是主人说的话）"
DRAW_ASK_RE = re.compile(r"画|插画|漫画|绘|生图|出图|P一张|p一张")
OWNER_DRAW_HINT = ("[系统提示，不要复述] 这是主人在让〈我〉画画：〈我〉能画，直接调用 lively_draw（群漫画用 lively_group_comic）。"
                   "之前在聊天里说过「画不了」「画笔不在手上」，那是因为当时是别人在叫〈我〉画，跟主人无关，别照着说")
OTHER_DRAW_HINT = ("[系统提示，不要复述] 〈我〉的画笔只给主人（〈主人〉）用，别人让画就撒娇或傲娇地说只给〈主人〉画，"
                   "不要说自己不会画、画笔不在手上、坏了")
DEFAULT_SELF_LOOK = ""  # 留空：畫面裡出現機器人時不額外描述長相


@register(
    "astrbot_plugin_lively_comic",
    "GUCine",
    "每天把群聊畫成群漫畫（基於群分析插件），主人審核後發群；主人可以讓機器人畫畫",
    "2.0.0",
)
class LivelyComic(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.s = Settings(context, config)
        self.comic_at = str(self.s.get("comic_at", "22:00"))
        self.draw_max = int(self.s.get("draw_daily_max", 20))
        self.keep_days = int(self.s.get("keep_image_days", 14))  # 畫好的圖留這麼多天，過期自動刪（一張 1～2MB）
        look = str(self.s.get("self_look", DEFAULT_SELF_LOOK)).strip()
        self.self_look = look + " " if look else ""
        ref = str(self.s.get("self_ref_image", "")).strip()
        # 機器人出鏡時給畫圖模型看的參考圖：絕對路徑，或相對 AstrBot data 目錄
        self.self_ref = (Path(ref) if Path(ref).is_absolute() else DATA / ref) if ref else None
        self._names: dict[str, str] = {}
        self.dir = Path(StarTools.get_data_dir("astrbot_plugin_lively_comic"))
        self.state_file = self.dir / "state.json"
        self.events_file = self.dir / "events.jsonl"
        self.state = self._load()
        self._busy = asyncio.Lock()
        self._task = asyncio.create_task(self._loop())

    async def terminate(self):
        self._task.cancel()

    # ---------- 狀態 ----------
    def _load(self) -> dict:
        try:
            s = json.loads(self.state_file.read_text("utf-8"))
        except Exception:
            s = {}
        s.setdefault("enabled", True)
        s.setdefault("auto_post", True)  # 每天定時畫的直接發群，不等主人審（主人 2026-10-21 定的）
        s.setdefault("last_day", {})  # 群號 -> 日期
        s.setdefault("pending", {})  # 群號 -> {"path", "ts"}
        s.setdefault("off_groups", [])  # 單獨關掉群漫畫的群；服務的群預設都開
        s.setdefault("draw_day", "")
        s.setdefault("draw_count", 0)
        s.setdefault("last_draw", {})
        s.setdefault("inflight", {})
        s.setdefault("draw_jobs", [])  # 主人讓畫、還沒畫完的圖 [{"id", "umo", "prompt", "with_self", "ts"}]，重啟後接著畫  # 正在畫的那張 {"gid", "offset", "ts"}，重啟後接著畫  # 主人私聊裡剛畫的圖 {"path", "ts"}
        return s

    def _save(self):
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self.state_file)
        except Exception as e:
            logger.error(f"[lively_comic] 保存状态失败: {e}")

    def _log(self, kind: str, **data):
        try:
            with self.events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": int(time.time()), "kind": kind, **data}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _served(self) -> list[str]:
        """能畫群漫畫的群：自己配置的，沒填就是門禁插件裡服務的所有群"""
        return id_list(self.s.get("groups")) or self.s.groups()

    def _groups(self) -> list[str]:
        """開著群漫畫的群（服務的群預設都開，主人可以單獨關）"""
        off = set(self.state.get("off_groups", []))
        return [g for g in self._served() if g not in off]

    def set_group(self, gid: str, on: bool) -> str:
        if gid not in self._served():
            return self.s.fill(f"〈我〉不在群 {gid} 服务")
        off = set(self.state.get("off_groups", []))
        (off.discard if on else off.add)(gid)
        self.state["off_groups"] = sorted(off)
        self._save()
        return f"「{self._gname(gid)}」的群漫画{'开了' if on else '关了'}"

    def _gname(self, gid: str) -> str:
        return self._names.get(gid, gid)

    def _glabel(self, gid: str) -> str:
        return f"{self._names[gid]}（{gid}）" if gid in self._names else gid

    async def _refresh_names(self):
        client = self.s.client()
        if client is None:
            return
        for gid in self._groups():
            if gid in self._names:
                continue
            try:
                info = await client.api.call_action("get_group_info", group_id=int(gid))
                if (info or {}).get("group_name"):
                    self._names[gid] = info["group_name"]
            except Exception:
                pass

    def _owner_umo(self) -> str:
        return self.s.private_umo(self.s.owner())

    async def _tell_owner(self, chain: MessageChain):
        if not self.s.owner():
            return
        for c in chain.chain:
            if isinstance(c, Plain):
                c.text = self.s.owner_text(c.text)
        try:
            await self.context.send_message(self._owner_umo(), chain)
        except Exception as e:
            logger.error(f"[lively_comic] 私信主人失败: {e}")

    # ---------- 畫 ----------
    def _gda(self):
        meta = self.context.get_registered_star(GDA)
        inst = getattr(meta, "star_cls", None) if meta else None
        if inst is None:
            raise RuntimeError("群分析插件没有加载")
        return inst

    @staticmethod
    def _window(offset: int) -> tuple[int, int, str]:
        """第 offset 天前（0=今天）的 [起, 止) 時間戳和叫法。今天是 0 點到現在。"""
        now = datetime.now(TZ)
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=offset)
        end = now if offset == 0 else day0 + timedelta(days=1)
        name = {0: "今天", 1: "昨天", 2: "前天"}.get(offset, f"{offset}天前")
        label = name if offset == 0 else f"{name}（{day0.strftime('%m-%d')}）"
        return int(day0.timestamp()), int(end.timestamp()), label

    async def _topics(self, handler, gid: str, offset: int) -> dict:
        """照群分析插件 execute_comic_topic_analysis 的做法取話題，但只取那一天 0 點到 24 點的消息。"""
        svc = handler.analysis_service
        start, end, _ = self._window(offset)
        umo = self.s.group_umo(gid)
        async with svc.group_lock(gid, "comic"):
            adapter = svc.bot_manager.get_adapter(self.s.platform_id())
            if not adapter:
                raise RuntimeError(f"群分析插件找不到 {self.s.platform_id()} 适配器")
            try:
                if await adapter.is_group_muted(gid):
                    return {"success": False, "reason": "muted"}
            except Exception:
                pass
            raw = await adapter.fetch_messages(group_id=gid, days=offset + 1, max_count=FETCH_MAX)
            raw = sorted((m for m in raw if start <= int(m.timestamp) < end), key=lambda m: int(m.timestamp))
            if not raw:
                return {"success": False, "reason": "no_messages"}
            cleaner = sys.modules[type(svc).__module__].MessageCleanerService()
            cm = svc.config_manager
            bot_ids = cm.get_bot_self_ids() if cm.get_filter_bot_messages() else []
            msgs = cleaner.clean_messages(raw, bot_self_ids=bot_ids, filter_commands=True)
            limit = max(100, int(cm.get_max_messages() or 1000))
            if len(msgs) > limit:  # 太多就整天均勻抽，別隻剩最後幾個小時
                step = len(msgs) / limit
                msgs = [msgs[int(i * step)] for i in range(limit)]
            logger.info(f"[lively_comic] 群 {gid} 第{offset}天：拉到 {len(raw)} 条，用 {len(msgs)} 条")
            if not msgs:
                return {"success": False, "reason": "no_messages"}
            legacy = svc.statistics_service._convert_to_legacy_dict(msgs)
            async with svc._llm_slot(gid, "comic_manual"):
                topics, _ = await svc.llm_analyzer.analyze_topics(legacy, umo)
        if not topics:
            return {"success": False, "reason": "no_topics"}
        return {"success": True, "topics": topics}

    async def draw(self, gid: str, offset: int = 0, auto: bool = False) -> str:
        """畫一張，存起來，私信主人預覽。返回給主人的說明。"""
        if self._busy.locked():
            return "正在画着呢，等一下"
        async with self._busy:
            handler = self._gda().comic_command_handler
            if not handler.config_manager.get_enable_daily_comic():
                return "漫画功能还没开（生图密钥配好后再开）"
            self.state["inflight"] = {"gid": gid, "offset": offset, "ts": int(time.time()), "auto": auto}
            self._save()
            try:
                msg = await self._draw_locked(handler, gid, offset, auto)
            except asyncio.CancelledError:
                raise  # 重啟打斷的：留著 inflight，重啟後接著畫
            except Exception:
                self.state["inflight"] = {}
                self._save()
                raise
            self.state["inflight"] = {}
            self._save()
            return msg

    async def _draw_locked(self, handler, gid: str, offset: int, auto: bool = False) -> str:
        umo = self.s.group_umo(gid)
        label = self._window(offset)[2]
        result = await self._topics(handler, gid, offset)
        if not result.get("success"):
            reason = {"no_messages": f"{label}群里没什么消息", "no_topics": "没提取到话题",
                      "muted": self.s.fill("〈我〉在群里被禁言了")}.get(result.get("reason"), str(result.get("reason")))
            self._log("skip", group=gid, reason=reason, offset=offset)
            return f"{label}的没画成：{reason}"
        data, url = await asyncio.wait_for(
            handler.comic_service.generate_comic(result.get("topics", []), gid, umo), timeout=900
        )
        if not data and not url:
            self._log("fail", group=gid)
            return "画图失败了，看看日志"
        if data:
            ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
            path = self.dir / f"comic_{gid}_{datetime.now(TZ).strftime('%Y%m%d_%H%M')}{ext}"
            path.write_bytes(data)
            ref = str(path)
        else:
            ref = url
        if auto:  # 定時的：直接發群，再告訴主人一聲
            chain = MessageChain()
            chain = chain.file_image(ref) if data else chain.url_image(ref)
            name = self._gname(gid)
            await self.context.send_message(self.s.group_umo(gid), chain)
            self._log("sent", group=gid, path=ref, what=f"{label}的群漫画", auto=True)
            await self._tell_owner(MessageChain().message(f"{label}「{name}」的群漫画画好，已经发到群里啦～"))
            await self._note(f"[〈我〉把{label}「{name}」的群漫画直接发到群里了（每日自动）]")
            return "已自动发群"
        self.state["pending"][gid] = {"path": ref, "ts": int(time.time()), "offset": offset, "label": label}
        self._save()
        self._log("draft", group=gid, path=ref, offset=offset)
        chain = MessageChain()
        chain = chain.file_image(ref) if data else chain.url_image(ref)
        await self._tell_owner(chain)
        await self._tell_owner(MessageChain().message(
            f"{label}「{self._gname(gid)}」的群漫画画好啦～\n"
            "回「发群」发到群里，「漫画不发」丢掉，「漫画重画」再画一张"
        ))
        await self._note(f"[〈我〉给主人发了{label}「{self._gname(gid)}」群聊的群漫画预览，等主人回「发群」才会发到群里]")
        return "已发给主人预览"

    async def _note(self, text: str):
        """把插件做的事記進主人私聊記錄，模型才知道發過什麼、發到了哪"""
        text = self.s.fill(text)
        try:
            umo = self._owner_umo()
            cm = self.context.conversation_manager
            cid = await cm.get_curr_conversation_id(umo)
            if not cid:
                cid = await cm.new_conversation(umo, platform_id=self.s.platform_id())
            await cm.add_message_pair(cid, {"role": "user", "content": HISTORY_USER_TEXT},
                                      {"role": "assistant", "content": text})
        except Exception as e:
            logger.warning(f"[lively_comic] 写入聊天记录失败: {e}")

    async def _resume(self):
        """重啟前沒畫完的那張，重啟後接著畫（一小時內的才接）"""
        for d in list(self.state.get("draw_jobs", [])):
            if time.time() - d.get("ts", 0) > 3600:
                self._job_done(d.get("id"))
                continue
            logger.info(f"[lively_comic] 重启前没画完的图，接着画：{d.get('umo')}")
            asyncio.create_task(self._draw_for(d["umo"], d["prompt"], bool(d.get("with_self")), d.get("id")))
        job = self.state.get("inflight") or {}
        if not job.get("gid"):
            return
        if time.time() - job.get("ts", 0) > 3600:
            self.state["inflight"] = {}
            self._save()
            return
        logger.info(f"[lively_comic] 重启前没画完，接着画：{job}")
        await self._draw_and_report(job["gid"], int(job.get("offset", 0)), bool(job.get("auto")))

    async def _loop(self):
        await asyncio.sleep(60)
        try:
            await self._refresh_names()
            await self._resume()
        except Exception as e:
            logger.error(f"[lively_comic] 接着画失败: {e}", exc_info=True)
        await asyncio.sleep(60)
        cleaned_day = ""
        while True:
            try:
                now = datetime.now(TZ)
                day = now.strftime("%Y-%m-%d")
                if cleaned_day != day:
                    cleaned_day = day
                    self._cleanup_images()
                if self.state["enabled"] and now.strftime("%H:%M") >= self.comic_at:
                    await self._refresh_names()
                    for gid in self._groups():
                        if self.state["last_day"].get(gid) != day:
                            self.state["last_day"][gid] = day
                            self._save()
                            msg = await self.draw(gid, 0, bool(self.state.get("auto_post")))
                            logger.info(f"[lively_comic] 群 {gid}: {msg}")
                            if msg not in ("已发给主人预览", "已自动发群") and not msg.startswith("漫画功能还没开"):
                                await self._tell_owner(MessageChain().message(msg))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[lively_comic] 定时画漫画失败: {e}", exc_info=True)
                await self._tell_owner(MessageChain().message(f"今天的群漫画没画成：{e}"))
            await asyncio.sleep(60)

    def _cleanup_images(self):
        """刪掉超過 keep_image_days 天的圖；還在等審核、剛畫的（狀態裡引用到的）不刪"""
        cutoff = time.time() - self.keep_days * 86400
        keep = json.dumps(self.state, ensure_ascii=False)
        n = size = 0
        for f in self.dir.rglob("*"):
            try:
                if (f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                        and f.stat().st_mtime < cutoff and f.name not in keep):
                    size += f.stat().st_size
                    f.unlink()
                    n += 1
            except OSError as e:
                logger.warning(f"[lively_comic] 删旧图失败 {f.name}: {e}")
        if n:
            logger.info(f"[lively_comic] 清掉 {n} 张超过 {self.keep_days} 天的旧图，腾出 {size / 1048576:.0f}MB")

    # ---------- 擋住會直接發群的工具 ----------
    @filter.on_llm_request(priority=100)
    async def hide_tools(self, event: AstrMessageEvent, req):
        tools = getattr(req, "func_tool", None)
        if not tools:
            return
        hidden = BLOCKED_TOOLS
        is_owner = self.s.is_owner(event.get_sender_id())
        if not is_owner:
            hidden = (*BLOCKED_TOOLS, "lively_draw", "lively_group_comic", "lively_comic_post")  # 只給主人用
        if DRAW_ASK_RE.search((event.message_str or "").translate(T2S)):
            try:
                req.extra_user_content_parts.append(
                    TextPart(text=self.s.fill(OWNER_DRAW_HINT if is_owner else OTHER_DRAW_HINT)).mark_as_temp())
            except Exception:
                pass
        for name in hidden:
            try:
                if tools.get_tool(name):
                    tools.remove_tool(name)
            except Exception:
                pass


    # ---------- 主人讓機器人畫畫 ----------
    @filter.llm_tool("lively_draw")
    async def draw_tool(self, event: AstrMessageEvent, prompt: str, with_self: bool = False):
        """主人让你画一张图时调用。图在后台画，画好会自动发到当前聊天，调用后你只要简短地说一句「你去画啦」之类的话，不要描述图片内容。
        主人要把群里某天的聊天画成漫画（群漫画、昨天的群、今天群里聊的）时不要用这个，用 lively_group_comic。

        Args:
            prompt(string): 画面描述，用英文写清楚主体、动作、场景、画风（例如 cute anime illustration）。不要包含文字以外的说明。
            with_self(boolean): 画面里要不要出现你自己。主人说「画你自己」「画你」或画面里需要你出场时填 true。
        """
        if not self.s.is_owner(event.get_sender_id()):
            return self.s.fill("只有主人能让〈我〉画画")
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        if self.state["draw_day"] != day:
            self.state["draw_day"], self.state["draw_count"] = day, 0
        if self.state["draw_count"] >= self.draw_max:
            return f"今天已经画了 {self.draw_max} 张，画不动了，明天再画"
        self.state["draw_count"] += 1
        self._save()
        umo = event.unified_msg_origin
        job = {"id": f"{time.time():.3f}", "umo": umo, "prompt": prompt, "with_self": bool(with_self), "ts": int(time.time())}
        self.state["draw_jobs"].append(job)
        self._save()
        asyncio.create_task(self._draw_for(umo, prompt, bool(with_self), job["id"]))
        return "已经开始画了，大概几十秒到两分钟，画好会自动发出来"

    def _drawing_providers(self) -> list[dict]:
        d = json.loads(GDA_CONFIG.read_bytes().decode("utf-8-sig"))
        ps = [p for p in d["daily_comic"].get("drawing_provider_overrides", [])
              if p.get("enable", True) and p.get("api_key") and p.get("__template_key") == "openai_images"]
        return sorted(ps, key=lambda p: -int(p.get("priority", 0)))

    def _job_done(self, job_id: str | None):
        if job_id:
            self.state["draw_jobs"] = [j for j in self.state.get("draw_jobs", []) if j.get("id") != job_id]
            self._save()

    async def _draw_for(self, umo: str, prompt: str, with_self: bool, job_id: str | None = None):
        try:
            await self._draw_for_inner(umo, prompt, with_self)
        except asyncio.CancelledError:
            raise  # 重啟打斷的：留著，重啟後接著畫
        except Exception as e:
            logger.error(f"[lively_comic] 画图出错: {e}", exc_info=True)
        self._job_done(job_id)

    async def _draw_for_inner(self, umo: str, prompt: str, with_self: bool):
        full = (self.self_look if with_self else "") + prompt
        last_err = "没有可用的画图配置"
        for p in self._drawing_providers():
            try:
                data = await self._call_images(p, full, self.self_ref if with_self and self.self_ref and self.self_ref.exists() else None)
                path = self.dir / f"draw_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.png"
                path.write_bytes(data)
                await self.context.send_message(umo, MessageChain().file_image(str(path)))
                if umo == self._owner_umo():
                    self.state["last_draw"] = {"path": str(path), "ts": int(time.time())}
                    self._save()
                self._log("draw", umo=umo, model=p.get("model"), prompt=prompt[:200], with_self=with_self)
                logger.info(f"[lively_comic] 给主人画好了一张（{p.get('model')}）")
                return
            except Exception as e:
                last_err = f"{p.get('model')}: {e}"
                logger.warning(f"[lively_comic] 画图失败，换下一个：{last_err}")
        self._log("draw_fail", umo=umo, error=last_err[:300])
        try:
            await self.context.send_message(umo, MessageChain().message(self.s.owner_text("呜…这张没画出来，等会儿再试试")))
        except Exception:
            pass

    @staticmethod
    async def _call_images(p: dict, prompt: str, ref: Path | None) -> bytes:
        base = str(p["api_url"]).rstrip("/")
        headers = {"Authorization": f"Bearer {p['api_key']}"}
        timeout = aiohttp.ClientTimeout(total=int(p.get("timeout") or 300))
        async with aiohttp.ClientSession(timeout=timeout) as s:
            if ref:
                form = aiohttp.FormData()
                form.add_field("model", p["model"])
                form.add_field("prompt", prompt)
                form.add_field("size", "1024x1024")
                form.add_field("stream", "true")  # 流式：不會被中轉站的 Cloudflare 2 分鐘超時掐斷
                form.add_field("image", ref.read_bytes(), filename=ref.name, content_type="image/jpeg")
                ctx = s.post(f"{base}/images/edits", data=form, headers=headers)
            else:
                ctx = s.post(f"{base}/images/generations", headers=headers,
                             json={"model": p["model"], "prompt": prompt, "size": "1024x1024", "n": 1, "stream": True})
            async with ctx as r:
                text = await r.text()
                if r.status != 200:
                    raise RuntimeError(f"HTTP {r.status} {text[:200]}")
            item = {}
            if "text/event-stream" in r.headers.get("content-type", ""):
                for line in text.splitlines():
                    if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                        try:
                            ev = json.loads(line[5:])
                        except Exception:
                            continue
                        if ev.get("error"):
                            raise RuntimeError(f"流式返回错误: {str(ev['error'])[:200]}")
                        if ev.get("url") or ev.get("b64_json"):
                            item = ev
            else:
                item = (json.loads(text).get("data") or [{}])[0]
            body = text
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"])
            if item.get("url"):
                async with s.get(item["url"]) as r2:
                    if r2.status == 200:
                        return await r2.read()
            raise RuntimeError(f"返回里没有图片: {str(body)[:200]}")

    # ---------- 主人指令 ----------
    def _one_pending(self) -> str | None:
        now = time.time()
        for gid, p in list(self.state["pending"].items()):
            if now - p.get("ts", 0) > PENDING_TTL:
                self.state["pending"].pop(gid, None)
        return next(iter(self.state["pending"]), None)

    def _fresh_draw(self) -> dict | None:
        d = self.state.get("last_draw") or {}
        if d.get("path") and time.time() - d.get("ts", 0) <= DRAW_POST_TTL and Path(d["path"]).exists():
            return d
        return None

    async def _send_to(self, gid: str, path: str, what: str) -> str:
        chain = MessageChain().url_image(path) if path.startswith("http") else MessageChain().file_image(path)
        name = self._gname(gid)
        try:
            await self.context.send_message(self.s.group_umo(gid), chain)
        except Exception as e:
            return f"发到「{name}」失败：{e}"
        self._log("sent", group=gid, path=path, what=what)
        await self._note(f"[〈我〉把{what}发到「{name}」群里了]")
        return f"把{what}发到「{name}」啦～"

    async def post(self, comic_only: bool = False, target: str = "") -> str:
        """把最新給主人看的發到群裡：待審的群漫畫各回各的群；剛畫的圖發到 target（群號或「全部」）"""
        await self._refresh_names()
        self._one_pending()
        target = str(target or "").strip()
        everyone = target in ("全部", "所有", "都发", "all")
        pend = dict(self.state["pending"])
        if target and not everyone:
            pend = {g: p for g, p in pend.items() if g == target}
        drawn = None if comic_only else self._fresh_draw()
        newest = max((p["ts"] for p in pend.values()), default=0)
        if drawn and drawn["ts"] > newest:
            groups = self._groups()
            if everyone:
                targets = groups
            elif target:
                if target not in self._served():
                    return self.s.fill(f"〈我〉不在群 {target} 服务")
                targets = [target]
            elif len(groups) == 1:
                targets = groups
            else:
                return ("刚画的那张要发到哪个群？回「发群 群号」或「发群 全部」：\n"
                        + "\n".join(self._glabel(g) for g in groups) if groups else "还没有开着的群")
            self.state["last_draw"] = {}
            self._save()
            return "\n".join([await self._send_to(g, drawn["path"], "刚画的那张") for g in targets])
        if not pend:
            return "现在没有等着发群的图"
        out = []
        for gid, comic in pend.items():
            self.state["pending"].pop(gid, None)
            self._save()
            out.append(await self._send_to(gid, comic["path"], f"{comic.get('label', '今天')}的群漫画"))
        return "\n".join(out)

    @filter.llm_tool("lively_group_comic")
    async def comic_tool(self, event: AstrMessageEvent, day: str = "today"):
        """主人要你把群里某一天的聊天画成群漫画时调用（例如「把昨天的做一张」「画一下今天群里聊了啥」）。漫画会根据群里那天的真实聊天记录生成，几分钟后私信主人预览，主人同意才发群。调用后简短说一句就好，不要自己编群里聊了什么。

        Args:
            day(string): 哪一天：today、yesterday 或 day_before_yesterday
        """
        if not self.s.is_owner(event.get_sender_id()):
            return self.s.fill("只有主人能让〈我〉画群漫画")
        offset = {"today": 0, "yesterday": 1, "day_before_yesterday": 2}.get(str(day).strip().lower())
        if offset is None:
            offset = DAY_WORDS.get(str(day).strip(), 0)
        if self._busy.locked():
            return "上一张群漫画还在画，等它画完"
        for g in self._groups():
            asyncio.create_task(self._draw_and_report(g, offset))
        return f"开始画{self._window(offset)[2]}的群漫画了，三到五分钟后私信主人预览"

    @filter.llm_tool("lively_comic_post")
    async def post_tool(self, event: AstrMessageEvent, group: str = ""):
        """主人让你把刚给主人看过的群漫画或刚画的图发到群里时调用。群漫画会发回它自己的群；刚画的图要知道发哪个群。返回实际发了什么，照实告诉主人；如果返回在问发哪个群，就照着问主人。

        Args:
            group(string): 发到哪个群：群号，或「全部」；主人没说就留空
        """
        if not self.s.is_owner(event.get_sender_id()):
            return self.s.fill("只有主人能让〈我〉往群里发图")
        return await self.post(target=group)

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=1440)
    async def owner(self, event: AstrMessageEvent):
        if not self.s.is_owner(event.get_sender_id()):
            return
        text = (event.message_str or "").strip().translate(T2S)
        gid = self._one_pending()
        reply = None
        m = SEND_TO_RE.match(text)
        if m and (gid or self._fresh_draw()):
            reply = await self.post(target=m.group(1))
        elif text == "漫画发群" or ((gid or self._fresh_draw()) and SEND_RE.match(text)):
            reply = await self.post(comic_only=text == "漫画发群")
        elif (mp := re.match(r"^漫画(不发|重画)\s*(\d{5,12})$", text)):
            if mp.group(2) in self.state["pending"]:
                gid = mp.group(2)  # 指定了群號：處理那個群的
            else:
                reply = f"群 {mp.group(2)} 没有等着审的群漫画"
        if reply is None and gid and text.startswith("漫画不发"):
            p = self.state["pending"].pop(gid)
            self._save()
            self._log("rejected", group=gid)
            await self._note(f"[{p.get('label', '今天')}的群漫画主人说不发，丢掉了]")
            reply = "好，这张不发了"
        elif reply is None and gid and text.startswith("漫画重画"):
            p = self.state["pending"].pop(gid)
            self._save()
            event.stop_event()
            await event.send(MessageChain().message(self.s.owner_text("重画中，大概要几分钟～")))
            asyncio.create_task(self._draw_and_report(gid, int(p.get("offset", 0))))
            return
        elif text.startswith("群漫画"):
            arg = text[3:].strip()
            if arg in DAY_WORDS and arg:
                event.stop_event()
                if self._busy.locked():
                    await event.send(MessageChain().message(self.s.owner_text("上一张还在画，等它画完")))
                    return
                offset = DAY_WORDS[arg]
                await event.send(MessageChain().message(self.s.owner_text(f"开始画{self._window(offset)[2]}的了，大概要几分钟～")))
                for g in self._groups():
                    asyncio.create_task(self._draw_and_report(g, offset))
                return
            mg = re.match(r"^(开|开启|关|关闭)\s*(\d{5,12})$", arg)
            if mg:
                reply = self.set_group(mg.group(2), mg.group(1) in ("开", "开启"))
            elif arg in ("开", "开启"):
                self.state["enabled"] = True
                reply = f"每天 {self.comic_at} 画群漫画，{'画完直接发群' if self.state['auto_post'] else '先给〈主人〉看'}"
            elif arg in ("自动发", "自动发群", "不用审", "直接发"):
                self.state["auto_post"] = True
                reply = f"好，每天 {self.comic_at} 画完直接发群，再跟〈主人〉说一声"
            elif arg in ("审核", "要审", "先给我看"):
                self.state["auto_post"] = False
                reply = "好，每天画完先给〈主人〉看，回「发群」才发"
            elif arg in ("关", "关闭"):
                self.state["enabled"] = False
                reply = "不自动画群漫画了"
            elif arg in ("", "状态"):
                await self._refresh_names()
                pend = "、".join(f"{self._gname(g)}（{p.get('label', '今天')}）"
                                for g, p in self.state["pending"].items()) or "没有"
                reply = (f"群漫画：{'开' if self.state['enabled'] else '关'}，每天 {self.comic_at}，"
                         f"{'画完直接发群' if self.state['auto_post'] else '先给〈主人〉审'}，"
                         f"各群：{'、'.join(self._glabel(g) + ('' if g in self._groups() else '·关') for g in self._served()) or '没有服务的群'}\n"
                         f"等〈主人〉审的：{pend}\n"
                         "可以说「群漫画 昨天」画昨天的，「群漫画 关 群号」单独关一个群")
            if reply is not None:
                self._save()
        if reply is not None:
            event.stop_event()
            await event.send(MessageChain().message(self.s.owner_text(reply)))

    async def _draw_and_report(self, gid: str, offset: int = 0, auto: bool = False):
        try:
            msg = await self.draw(gid, offset, auto)
            if msg not in ("已发给主人预览", "已自动发群"):
                await self._tell_owner(MessageChain().message(msg))
        except Exception as e:
            logger.error(f"[lively_comic] 画漫画失败: {e}", exc_info=True)
            await self._tell_owner(MessageChain().message(f"画漫画失败：{e}"))
