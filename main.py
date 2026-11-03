"""每日群漫畫：每天到點把各群當天的聊天挑幾件事，一件事畫一張四格漫畫（10-30 起；以前是一群一張），畫好一張一張給〈我〉看（comic_look），
跟圖配什麼話她定（當天的簡單總結，不提改過；10-29 起直接發群、不私信主人）；到點一定發（10-26 晚起不再有「看過不發」）。
每天那輪分三段（10-26 晚用戶定）：到點前 comic_prep_min 分鐘各群一起取話題（取不到隔一分鐘再試，最多 comic_topic_tries 次，
最晚試到到點前 comic_draw_min 分鐘）；拿到話題就畫第一張；畫好給〈我〉看，哪格不對她可以提出來修圖（在這張上改）或重畫
（改分鏡整張重畫），每張最多改 comic_fix_max 次（群漫畫畫幾張不算進每天的張數上限，10-31 用戶定；張數照樣記），到點前改好再給她看、用哪張她定，沒改好就照原樣；到 comic_at 一起發。
私信主人的話都是她自己寫的：插件只把發生的事交給她，說不說、怎麼說她定（10-26 用戶定）。

畫漫畫用的是「群分析總結」插件（SXP-Simon/astrbot_plugin_qq_group_daily_analysis）的內部服務和畫圖配置，
分鏡由〈我〉自己定（11-02 起沒有退路：分鏡寫壞了先請她重寫一次，還是壞就那晚那個群沒有群漫畫，不再退回那個插件畫長圖）。那個插件自己的定時分析、自動漫畫都關著，它會直接往群裡髮長圖的 LLM 工具也擋著。

畫圖工具 lively_draw：主人和〈我〉好感度 draw_min_score 以上的人才有，畫好發到當前聊天或 TA 的私聊（每天最多 draw_daily_max 張）。
  10-27 起她理解成用自己的手機拍照、截屏（phone.py）：拍法（自拍／隨手拍／截圖／其他）、畫風（二次元／真人 cos）、形狀（方直橫）、
  帶哪些參考素材（資料目錄 refs/，refs.json 列名字和說明；畫到群友寫 QQ 號）都是她選；帶參考圖走中轉站 /images/edits 的 JSON（一次能帶好幾張）。
群漫畫畫到誰就帶 TA 定做的形象或 QQ 頭像當參考圖（最多 10 張）。lively_avatar（avatar.py）：群友定做自己的虛擬形象，
  准备→TA 之後確認→画三视图，每人一次，再做要主人放行；主人說話的聊天裡寫 qq 可以替別人做（10-29）。
lively_comic_post：〈我〉把圖冊裡指定編號的一張發到群裡（11-02 起一定寫編號，不再默認「最後畫的那張」）；〈主人〉私聊拍的照片、群漫畫整頁（只發回它自己的群）能發；lively_pic 看圖冊、把圖拿給這個聊天的人看。圖冊見 gallery.py。
先看再發（11-02）：〈主人〉說某個群先給他看，她在主人私聊調 lively_comic_hold（先看／放行／不发了），下一組畫好（定時、補畫都一樣）在 _publish 的檢查點存著不發，hold 只管一次，存著的 48 小時沒放行就不發並告訴她。
lively_comic_redo：補畫、重畫某個群某天的群漫畫（10-28 起誰請都行、她自己想畫也行；10-31 起張數上限只管她自己要畫的，〈主人〉在對話裡直接要的不算）：照每天那張的做法取話題、她寫分鏡和名字牌、
畫好先給她看、哪格不對可以改，看完就發到那個群，不等到點；一天最多 comic_redo_max 張（10-27 用戶要的：
10-26 晚桐群那張沒畫成，她只能拿 lively_draw 自己寫提示詞補一張方圖，沒有話題、名字牌，畫完也沒看）。

發送（10-28）：10-27 22:00 四個群同一秒發 2.6MB 的 PNG，NapCat 等 20 秒報 retcode=1200 超時，三張被當成沒發，
  其實 22:00:25～50 都到了；她跟主人說沒發出去，隔天早上補畫，桐群、純良各收了兩張。現在大圖先轉 JPEG、各群排隊發（隔 SEND_GAP 秒），
  報超時先翻群裡的消息看到了沒有，到了算發成（記 late），沒到才再發一次；真的沒發成圖留著（pending，兩天），lively_comic_post 能發。
  畫圖那步失敗、離發還來得及就隔 DRAW_RETRY_GAP 秒再畫（10-27 小凛群 21:22 兩個模型都報錯，就沒畫了）。
  補畫分兩種：補「那天定時那張沒畫成」的，每群每天一次、不算 comic_redo_max；那天已經發過的要寫 again 才再畫、算張數。

主人私信指令：群漫畫 開 / 關 / 狀態；群漫畫 開 群號 / 群漫畫 關 群號（單獨開關某個群，服務的群預設都開）
（10-26 拿掉了手動補畫、先審後發、「發群」攔截這幾條；10-27 起補畫交給她用 lively_comic_redo）
"""
import asyncio
import base64
import contextlib
import hashlib
import json
import os
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

from .lively_common import ASK_OWNER, CONFIG_DIR, DATA, Settings, T2S, id_list, note_outbox
from .avatar import Avatars
from .gallery import Gallery, SINGLE_KINDS
from .phone import MAX_REFS, Phone
from . import see

HOLD_TTL = 48 * 3600  # 已经存着的那组：这么久没放行就不发了（到期告诉她一声）；设了「先看」没用上的另算，管到次日 06:00（_hold_until）
PENDING_TTL = 48 * 3600  # 畫好沒發成的群漫畫留多久（lively_comic_post 能發）
WRAP_MAX = 3  # 圖發完之後她另外說的話，最多幾條（10-31 用戶定：總結是為了快速了解，不能長篇）
WRAP_LEN = 30  # 提示她每條大約多少字以內；程式硬截 2 倍
WRAP_RULE = """
[群漫画发完之后〈我〉在群里说的话]
下面是〈我〉刚发到群里的群漫画，每张画的什么事。图已经发出去了，现在〈我〉另外在群里说几句。
这几句的作用是让群友快速了解今天群里聊了什么，所以要短：说几条、每条说什么〈我〉自己定，最多 {mx} 条，每条 {n} 个字以内，不用每张图都说一遍，不复述剧情，不堆语气词；没什么好说的就空着。
用〈我〉平时在群里说话的样子。
只输出 JSON：{{"say": ["第一条", "第二条"]}}，不说就 {{"say": []}}"""
SEND_GAP = 10  # 每天那輪各群排隊發，中間隔幾秒（10-27 四個群同一秒發大圖，NapCat 三個報超時）
SEND_CHECK = (10, 25, 40)  # 發送報超時之後，隔這些秒翻群裡的消息看到了沒有
JPEG_OVER = 1_200_000  # 比這大的 PNG 發之前轉 JPEG（10-27 1.2MB 那張 8 秒發完，2.6MB 的都超時）
DRAW_RETRY_GAP = 120  # 畫圖那步失敗，隔多久再畫
DRAW_RETRIES = 2
GDA = "astrbot_plugin_qq_group_daily_analysis"
BLOCKED_TOOLS = ("group_daily_analysis_trigger",)  # 會直接髮長圖到群裡，跳過主人審核
TZ = timezone(timedelta(hours=8))
GDA_CONFIG = CONFIG_DIR / f"{GDA}_config.json"
FETCH_MAX = 4000  # 一天能有一千多條，拉夠整天再均勻抽樣
# 取話題時〈我〉的消息換成這個 ID 交給群分析插件（10-31）：它按 bot_self_ids 把〈我〉說的整段濾掉，
# 話題模型只看到主人對著空氣說話，群裡另一個叫「大肥鱼…」的號就被當成主人在跟她聊
ME_ID = "ME"
HISTORY_USER_TEXT = "（系统记录：群漫画插件做的事，不是主人说的话）"
DRAW_ASK_RE = re.compile(r"画|插画|漫画|绘|生图|出图|P一张|p一张")
OWNER_DRAW_HINT = ("[系统提示，不要复述] TA 在说画画的事：〈我〉现在能给 TA 画。"
                   "之前聊天里说过「画不了」「画笔不在手上」，是对当时还不能画的人说的")
OTHER_DRAW_HINT = ("[系统提示，不要复述] 〈我〉现在不能给 TA 画：画笔只给〈主人〉和〈我〉好感度 {min} 以上的人用，TA 还不到；"
                   "画笔没坏，〈我〉也会画")
OFF_DRAW_HINT = "[系统提示，不要复述] 〈我〉现在不能画图：聊天里画图在后台关着（〈主人〉在面板关的）"
# 說到群漫畫時臨時帶給她的事實（10-29 20:50 主人私聊：她記成「九点前把群漫端给爹爹」、以為要自己動手畫，一直問是哪個群）
COMIC_ASK_RE = re.compile(r"群漫|漫画")
DRAWN_KEEP = 2 * 3600  # 每個聊天剛畫的圖記多久（說說配「刚画的」那張）
HELD_MSG = "已存着等主人看"
DONE_MSGS = ("已自动发群", HELD_MSG)  # 這幾種已經跟主人說過了
TOPIC_RETRY_GAP = 60  # 每天那張取不到話題（群分析插件的模型超時之類），隔這麼久再試
DRAW_LOW = 3  # 聊天裡畫圖剩這麼幾張以下，回傳多說一句「快用完了」
DRAW_SHARE = "聊天里画的、说说配图、定做形象一起算，每天的群漫画不算"  # 每天畫圖張數怎麼算（被擋時照實寫）
SEE_MAX = 1024  # 畫好的圖交給她看時長邊縮到多大
SEE_MARKS = ("[Image from tool 'lively_draw'", "[Image from tool 'lively_avatar'")  # AstrBot 把工具回的圖接成一條 user 消息，開頭是這句
SEE_EN_RE = re.compile(r"Image returned and cached at path='[^']*'\. Review the image below\. Use send_message_to_user[^\n]*?path='[^']*'\."
                       r"|图缓存在 path='[^']*'，在下面给你看。")  # 后一种是 gate 换过的（10-29 18:5x）
TOOL_WAIT = 100  # 畫圖工具最多等這麼久再回她（AstrBot 一次工具最多等 120 秒），等不到就轉背景畫
# 跟圖一起發的那句話裡的內部標記（表情包標籤、系統提醒、工具標記）發之前拿掉：
# 10-29 她在 text 裡寫了「&&happy&&」，原樣連圖一起發出去，發完複查把那一條（連圖）撤了
LEAK_RE = re.compile(r"&&[A-Za-z][\w-]{0,30}&&|<system_reminder>.*?(?:</system_reminder>|$)|<[^<>]{0,8}DSML.*$|</?[a-zA-Z_][^<>]{0,40}>",
                     re.S)
DRAW_SECS_GUESS = 180  # 估改一次要多久：沒量到這個群第一張畫了多久時，當一張要這麼久（10-26 實際 2～3.5 分鐘）
FIX_SB_SECS = 60  # 重畫要先改分鏡
FIX_LOOK_SECS = 60  # 改好再給她看一遍
FIX_MIN_WAIT = 30  # 改的那張至少等這麼久（離發的時間更短時）
REDO_DAYS = {"前": 2, "昨": 1}  # 補畫哪天：「昨天」「前天」，其他都當今天
# 修圖：把畫好的那張交給畫圖模型的 edits 介面，只改她說的地方；她的意見是中文，原樣帶上
EDIT_PROMPT = ("Edit this comic page. Keep the panel layout, every character's look, the art style, the colors and all the other "
               "text exactly as they are; change only what is asked below (the request is written in Chinese).\n"
               "Change: {change}\n"
               "Render any Chinese text exactly as written in the request; do not add any other text, numbers or English words.")
# 修圖時她寫到的人帶上 TA 的定做形象（沒有就 QQ 頭像），照著畫（10-28：她把祈改成分鏡瞎編的黑長髮）
EDIT_PEOPLE = ("\nImage 1 is the comic page to edit. The other images are only references for how these people look; "
               "draw them in the comic page's own art style:\n{lines}\n"
               "These people's looks (hair, eyes, face, clothes, accessories) come only from their reference images; "
               "ignore any description of their looks in the request.")
EDIT_PEOPLE_MAX = 4
# 定做形象的描述（她寫的「hair: … / eyes: …」）挑這幾欄給分鏡、看圖用
MADE_KEYS = ("hair", "eyes", "outfit", "accessories", "features")


def made_brief(desc: str, n: int = 90) -> str:
    """定做形象的描述縮成一句中文：髮型、眼睛、衣服、配件、特徵；不是那個格式就原樣截短"""
    parts = {}
    for seg in str(desc or "").split("/"):
        k, sep, v = seg.partition(":")
        if sep and k.strip().lower() in MADE_KEYS and v.strip():
            parts[k.strip().lower()] = v.strip()
    text = "，".join(parts[k] for k in MADE_KEYS if k in parts) or str(desc or "").strip()
    return text if len(text) <= n else text[:n - 1] + "…"

# 拍好了的工具回傳最後接這句：只講事實和代價（10-30 她看完第一張想補一句話，卻又叫了一次拍照）
DRAW_DONE_NOTE = "\n这次拍照做完了：要接着说话就直接写在回复里；再调 lively_draw 会再拍一张、再发一张、再算一张的张数和钱"

class _AnyLocked:
    """面板試畫前看「有沒有哪個群正在畫」：各群的鎖有一把鎖著就算（以前只有一把鎖，面板讀的是 _busy.locked()）"""
    def __init__(self, locks: dict):
        self._locks = locks

    def locked(self) -> bool:
        return any(lk.locked() for lk in self._locks.values())


def draw_fail_reason(err: str) -> str:
    """畫圖出錯的原因，說成她看得懂的話"""
    low = (err or "").lower()
    if "safety" in low or "moderation" in low or "审核" in err:
        return "被审核拒了，画面里多半有露骨或者不让画的内容"
    if "timeout" in low or "超时" in err:
        return "画图那边太久没回"
    if "没有可用的画图配置" in err:
        return "现在没有能用的画图配置"
    return "画图那边出错了"


STORYBOARD_BAD = "分镜写坏了："


def fix_json(text: str) -> str:
    """本地修一段「差一點就能解析」的 JSON（11-02）：只取第一個 { 起；去 ```；字串外補缺的逗號、去尾逗號、補沒收的引號和括號。
    不改任何字的內容；修不好的（引號沒轉義等）照樣拋 ValueError 給呼叫的人"""
    t = re.sub(r"```(?:json)?", "", text or "")
    i = t.find("{")
    if i < 0:
        raise ValueError("分镜不是 JSON")
    out, stack, in_str, esc, prev = [], [], False, False, ""
    for ch in t[i:]:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str, prev = False, '"'
            continue
        if ch.isspace():
            out.append(ch)
            continue
        if ch == '"':
            if prev in ('"', "}", "]") or prev.isalnum():  # 上一個值收了、下一個直接是字串：缺逗號
                out.append(",")
            in_str = True
        elif ch in "{[":
            if prev in ('"', "}", "]") or prev.isalnum():
                out.append(",")
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            while out and (out[-1].isspace() or out[-1] == ","):
                if out[-1] == ",":
                    out.pop()
                    break
                out.pop()
            if stack:
                stack.pop()
            if not stack:
                out.append(ch)
                break
        out.append(ch)
        prev = ch
    if in_str:
        out.append('"')
    s = "".join(out)
    while s.rstrip().endswith(","):
        s = s.rstrip()[:-1]
    s = s.rstrip().rstrip(":").rstrip()
    return s + "".join(reversed(stack))


class StoryboardBad(RuntimeError):
    """分鏡 JSON 壞了、請模型重寫一次還是壞（11-02）：整個分鏡就沒了，不退回群分析插件"""


STORYBOARD_REPAIR = """下面是一段要当 JSON 解析的文字，解析时报错：{err}
请把它修成能解析的合法 JSON：缺的逗号、引号、括号补上，被截断的地方在最近的完整位置收尾；内容一个字都不改、不增不减，只输出修好的 JSON，不要解释。

{text}"""


def comic_fail_reason(err: str) -> tuple[str, bool]:
    """每天那張畫圖那步沒成的原因（_draw_any 把每個模型的錯用「；」接起來），說成她看得懂的話；第二個值：隔一會再畫有沒有用。
    10-27 晚小凛群只交給她「画图那步失败了」，主人問為啥掛了她答不出（實際：兩個模型都超時；有個群是一張參考圖中轉站讀不了）"""
    parts = [x for x in (err or "").split("；") if x.strip()] or [err or ""]
    low = (err or "").lower()
    if "safety" in low or "moderation" in low or "审核" in err:
        return "被 OpenAI 审核拒了（多半是画面太荤或者有不让画的内容）", False
    if "参考图" in err or "invalid image" in low or "image_parse" in low:
        return "有张参考图中转站读不了", False
    if all("timeout" in x.lower() or "timed out" in x.lower() or "超时" in x for x in parts):
        return ("画图中转站两个模型都超时了" if len(parts) > 1 else "画图中转站超时了"), True
    if "没有可用的画图配置" in err:
        return "现在没有能用的画图配置", False
    if "张已经画完了" in err or "张用完了" in err or "一天最多" in err:  # 10-31 被張數擋住的照實說是張數，不說成中轉站壞了
        return f"是今天的张数额度用完了，不是画图那边坏了（{err[:80]}）", False
    return f"画图中转站出错了（{err[:80]}）", True


DEFAULT_SELF_LOOK = ""  # 留空：畫面裡出現機器人時不額外描述長相
# 群漫畫的分鏡（10-25 起自己做，不用群分析插件那套「有幾個話題畫幾格、每格都要有〈我〉、群友畫成白團子」）：
# 用〈我〉的人格挑今天值得畫的事，重要的人標〈我〉給 TA 起的稱呼。
# 10-30 起照四格漫畫的樣子（用戶給了一張參考）：一件事畫一張，頂上標題、3～4 格從上往下排；畫幾件〈我〉定
STORYBOARD_RULE = """
现在〈我〉要把今天群里的事画成群漫画，发到群里给大家看。下面有今天的话题和今天出场的人。
- 一件事画成一张竖着的四格漫画：顶上一个标题，下面 {lo}～{hi} 格从上往下排，几格〈我〉定，一格一个瞬间，几格连起来把这件事讲完（开头、发展、转折、收尾那样）
- 画几件事〈我〉自己定，挑今天真正好玩、值得画的，不用每个话题都画；今天最多画 {most} 件（{why}）
- 话题下面附了相关的原话（照时间排，「……」是中间隔开了，[图片：…] 是那张图里的内容）。话题是别的程序归纳的，有时会把不相干的几段聊天并成一个：画之前对照原话，只画真正连在一起的那段，不相干的别硬接成一件事；谁说了什么、对谁说、说的是哪件事，照原话来，不要安到别人头上或别的事上
- 每格写清楚谁在场：只画出场名单里的人，用「称呼」那栏的叫法（〈我〉平时怎么叫 TA），不要写 QQ 号；〈我〉有参与的格才画〈我〉
- 台词短（每句不超过 15 个字），是那个人会说的话的样子，别照抄原话，也别借台词损人；〈我〉的台词用〈我〉自己的口吻
- 「〈我〉」是〈我〉的自称：别人跟〈我〉说话、提到〈我〉时，照 TA 们平时叫〈我〉的叫法写（多半是「〈名字〉」），不要写成「〈我〉」
- 不画政治、不画色情，不拿谁的长相、身材开玩笑
- 给出场的每个人定一个简单好认的样子（发色、发型、一个配饰），用英文写，所有几张里保持一样；名单里标了「有定做的形象」的人 look 写空字符串（画的时候照 TA 的形象图画，长相不用写）；标了「头像不是人」的人没有能照着画的图，就照〈我〉写的 look 画，样子〈我〉定，跟其他人的发色、打扮明显不一样
- scene 里提到人一律用称呼，不写长相（不写「灰发男孩」「蓝发女孩」这种）
- 所有人都画成和〈我〉差不多年纪的 Q 版年轻人，不画成大叔、长辈；〈我〉管〈主人〉叫「〈主人〉」只是昵称，他也是年轻群友的样子，头上标的是他的群名片
只输出 JSON：{{"cast": [{{"称呼": "…", "look": "English, short"}}], "strips": [{{"title": "这件事的标题，不超过 10 字", "topic": "画的是哪个话题", "panels": [{{"scene": "English visual description of the moment", "who": ["称呼", "…"], "me": true, "lines": [{{"who": "称呼或〈我〉", "say": "台词"}}], "caption": "这一格旁边的小注，不超过 12 字，没有就空字符串"}}]}}]}}"""
# 重畫一張（她看了要改）：只改這一件事的那張
STORYBOARD_ONE = """
这次只重写一件事的那张（{lo}～{hi} 格），输出的 strips 里只放这一张。"""
# 每天那張畫好先給〈我〉看（comic_look，10-26 用戶定）：看圖的模型要認得圖，配什麼話、要不要改她定；只講事實。
# 10-26 晚起到點一定發（她自己在主人私聊說「到点该发就得发…赶不上就照发，事后错的那句本鱼自己补一句更正」）：
# 不再有「看過不發」，有錯可以改，來不及改就照原樣發，那句話裡可以順手更正
LOOK_RULE = """
[〈我〉看{day}的群漫画]
{intro}下面有{day}群里的话题（谁在聊）和〈我〉画之前写的分镜（有的话），图在最后。
要核对的是两件事：画的是不是群里{day}真聊过的话题；台词、名字牌，还有画面里谁在做什么（谁在抽烟、谁晕了、谁在劝），是不是落在真说了、真做了那些事的人身上（没有把 A 的话、A 的事安到 B 头上）；名字牌底下的人是不是那个人的样子（同一个人每格的发色、衣服都一样）。话题和分镜都没留下（比如重启前画好的）就没什么可核对。
画面上的小毛病不算画错：字有点歪、名字牌写错个把字、多一只手、少条尾巴、人画走样、背景不对、台词和分镜差几个字。
{fix}
{send}图发完之后，话另外再发：〈我〉看完所有张再决定在群里说什么，这里写的 text 只是草稿，写得很短（十几个字），没话说就空；画的过程（改没改过、修过哪里）不用提。
只输出 JSON：{{"看到的": "一两句：这张画了什么事、谁说了什么、谁在做什么", {pick}{fixf}"text": "这张图的一句话草稿，很短，不想说就空字符串", "why": "一句：为什么这么定"}}"""
LOOK_INTRO = "这是〈我〉今天给群「{name}」画的群漫画{strip}，画好了还没发，到 {at} 会发出去。"
LOOK_INTRO_REDO = "这是{asker}请〈我〉补画的群「{name}」{day}的群漫画{strip}，画好了还没发，〈我〉看完就发出去。"
LOOK_SEND = "这张会直接发到群里，不用先给〈主人〉看；图先发，话在图发完之后另外发。"
# 10-30 用戶定：幾張拼成一張原尺寸的大圖再發（之前一張一張發）
LOOK_SEND_ALL = ("今天这 {n} 张会照顺序拼成一张大图（原尺寸，不缩小）直接发到群里，不用先给〈主人〉看；"
                 "图先发，话在图发完之后另外发。")
LOOK_HOLD = ("〈主人〉说这个群的先给他看：这组画好了先存着不发，〈主人〉点头了才发；图先存，话等发的时候再说。"
             "这一张该核对、该改还是照常，text 这次可以空着。")
LOOK_PICK = '"用哪张": "改过的 或 原来的", '  # 看改過的那張時才問
LOOK_FIX = '"怎么改": "修图、重画，不改就空字符串", "改什么": "要改的话：第几格、哪里、改成什么样", '  # 這次能改才問
# 看圖時告訴她能不能改、改一次多久、離發還有多久（只講事實；改不改她定）
FIX_NOTE = ("画面里哪里不对，〈我〉可以先改，改不改〈我〉定：「修图」是在这张图上只改〈我〉写明的地方，没写到的都照旧，"
            "适合改名字牌、台词、气泡指错了人、多画或少画了什么；只写换台词的话，画面里谁在抽烟、谁晕着这些动作不会跟着换；"
            "只写换名字牌的话，牌子底下还是原来那个人的长相；要换人、换动作，写明每格画成谁、在做什么，"
            "写到人时写 TA 的 QQ 号或 QQ 昵称（下面每个名字牌后面写着，名字牌上的字不认），写到的人 TA 定做的形象（没有就 QQ 头像）会一起带给画图的，长相只照那张图画，〈我〉写的发色、衣服这些不会用；{redraw}改一次要再画一张图，大概 {per} 分钟；{until}，"
            "这张今天还能改 {k} 次。要改的话，text 这次先空着：改好了会再给〈我〉看一遍，那时再写；"
            "到 {at} 还没改好就把这张原样发出去，没改成也会告诉〈我〉为什么，那时再写。")
FIX_REDRAW = "「重画」是照〈我〉说的先改分镜、再整张重新画，适合整格画错、话题或人要换，别的格也会跟着变样，还要多一分钟改分镜。"
FIX_NO_REDRAW = "这张没留下分镜，只能修图。"
# 群漫畫那邊出的事（沒畫成、取不到話題）：插件不替她寫句子，把事實交給她，私信不私信、怎麼說她定（10-26 用戶定）
REPORT_RULE = """
[群漫画那边的事]
下面是后台发生的事（事实，不是谁对〈我〉说的话）。要不要私信〈主人〉说一声、怎么说由〈我〉定，用〈我〉平时跟〈主人〉说话的样子；不想说就空着。
只输出 JSON：{"say": "私信〈主人〉的话，不说就空字符串"}"""
# 每格只畫分鏡寫到的人（10-31 三個模型都把全員排成一排、每格都畫）
PANEL_ONLY = " No one else is in this panel."
# 四格漫畫的版面：頂上標題，格子一格佔滿一整列、從上往下排（10-30 照用戶給的參考）
COMIC_LAYOUT = ("a vertical yonkoma (4-koma) comic strip: a hand-lettered title at the very top, then {n} wide panels of equal "
                "height stacked from top to bottom, each panel spanning the full width")


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
        self._locks: dict[str, asyncio.Lock] = {}  # 群號 -> 鎖：各群同時畫，同一個群不畫兩張
        self._busy = _AnyLocked(self._locks)  # 面板試畫前看「有沒有哪個群正在畫」
        self._gen_sem: asyncio.Semaphore | None = None  # 每天那輪同時取話題、畫圖的群數（comic_parallel）
        self._waiting: set[str] = set()  # 工具還在等結果的畫圖 job
        self._seen: dict[str, str] = {}  # job / 聊天 -> 剛畫好的圖在哪：工具回傳時帶給她看
        self._sb: dict[str, tuple] = {}  # 群號 -> (分鏡, 出場的人)：自己的分鏡畫的那張，看圖時給她對照
        self._draw_secs: dict[str, float] = {}  # 群號 -> 今天第一張畫了幾秒：估她想改時來不來得及
        self._redo: dict[str, dict] = {}  # 群號 -> 正在補畫的那張 {"due", "origin", "ts"}：不等到點，改到 due 為止
        self._bg: set[asyncio.Task] = set()  # 背景補畫的任務（留著引用，免得跑到一半被回收）
        try:  # 她電腦「素材」資料夾在容器裡的位置：drawn 連結過去的地方的上一層（圖冊.txt 放那裡，她翻得到）
            root = Path(os.path.realpath(self.drawn_dir)).parent if self.drawn_dir.is_symlink() else None
        except OSError:
            root = None
        self._gallery = Gallery(self.dir, root, self._gname)  # 圖冊（11-02）：每張圖一個編號，發圖一定寫編號
        self.phone = Phone(self)  # 手機拍照：參考素材、群友的頭像和定做的形象
        self.avatars = Avatars(self)  # 群友定做自己的虛擬形象（lively_avatar）
        self._task = asyncio.create_task(self._loop())
        self._watch = see.Watcher(self)  # 白天開著群漫畫的群收到圖就先看（10-31 用戶定「白天边收边看」）
        self._watch_task = asyncio.create_task(self._watch.run())

    async def terminate(self):
        self._task.cancel()
        self._watch_task.cancel()

    @filter.event_message_type(filter.EventMessageType.ALL, priority=sys.maxsize + 2)
    async def watch_images(self, event: AstrMessageEvent):
        """只看不攔：開著群漫畫的群裡別人發的圖，丟給背景去看"""
        try:
            gid = str(event.get_group_id() or "")
            if not gid or gid not in self._groups() or str(event.get_sender_id()) == self._me_qq():
                return
            for mid, url in see.live_images(event):
                self._watch.offer(mid, url)
        except Exception as e:
            logger.debug(f"[lively_comic] 白天收图出错：{e}")

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
        s.setdefault("hold", {})  # 群號 -> {"since"}：〈主人〉说这个群的下一组画好先存着不发（只管一次）
        s.setdefault("held", {})  # 群號 -> {"page", "ts", "day", "label", "redo", "looks"}：存着等〈主人〉看的那一組（圖冊整頁編號）
        s.pop("last_draw", None)  # 11-02 起發圖一定寫圖冊編號，不再記「最後一張」
        s.pop("last_post", None)
        s.pop("drawn", None)
        s.setdefault("inflight", {})  # 群號 -> 正在畫的那張 {"gid", "offset", "ts", "auto", "path"?}，重啟後接著畫
        if "gid" in s["inflight"]:  # 以前一次只畫一個群，存的是那一張本身
            s["inflight"] = {str(s["inflight"]["gid"]): s["inflight"]}
        s.setdefault("redo_day", "")
        s.setdefault("redo_count", 0)  # 今天補畫了幾張（lively_comic_redo）
        s.setdefault("makeup", {})  # "日期:群號" -> 補畫的時間：補那天定時那張沒畫成的，每群每天一次、不算張數
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
            return f"群 {gid} 不是她服务的群"
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
        for gid in self._served():
            if gid in self._names:
                continue
            try:
                info = await client.api.call_action("get_group_info", group_id=int(gid))
                if (info or {}).get("group_name"):
                    self._names[gid] = info["group_name"]
            except Exception:
                pass

    @property
    def comics_dir(self) -> Path:
        """群漫畫 comics/<群號>/：10-29 起是她電腦「素材\\群漫画」（連結過去）"""
        return self.dir / "comics"

    def me_ref(self) -> Path | None:
        """畫〈我〉帶的參考圖：她的形象（參考素材「我」那張，女僕裝三視圖）；沒有才用設定 self_ref_image（10-29 用戶定先參考形象）"""
        ph = getattr(self, "phone", None)
        try:
            x = ph._item("我") if ph else None
            f = ph._file(x["file"]) if x else None
        except Exception:
            f = None
        if f:
            return f
        ref = getattr(self, "self_ref", None)
        return ref if ref and ref.exists() else None

    @property
    def drawn_dir(self) -> Path:
        """聊天裡畫的圖：她電腦「素材\\画的图」"""
        return self.dir / "drawn"

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

    async def _report(self, facts: str):
        """群漫畫那邊出的事（沒畫成之類）：不替她寫句子（10-26 22:08 私信主人「今天的没画成：没提取到话题」，
        沒說哪個群，也不是她的話）。把事實交給她，私信不私信、怎麼說她定；說了就發、記進待讀消息（門禁插件下一輪
        帶給她），沒說或沒問成就只記進主人私聊的記錄，主人問起她知道"""
        facts = self.s.fill(facts)
        say = ""
        try:
            say = await self._her_words(facts)
        except Exception as e:
            logger.warning(f"[lively_comic] 问她要不要跟主人说没问成：{e}")
        if say and self.s.owner():
            await self._tell_owner(MessageChain().message(say))
            note_outbox(self._owner_umo(), say, "群漫画")
        else:
            await self._note(f"[〈我〉这边：{facts}（没私信〈主人〉）]")
        self._log("report", facts=facts[:300], said=say)

    async def _her_words(self, facts: str) -> str:
        """把事實交給〈我〉（人設＋REPORT_RULE），回她想私信主人的話（不想說是空字串）"""
        pid = "look_provider_id" if self.s.get("look_provider_id") else "storyboard_provider_id"
        prov = self.s.provider(pid)
        if prov is None:
            raise RuntimeError("没有能用的模型")
        resp = await asyncio.wait_for(prov.text_chat(prompt=facts, system_prompt=self.s.persona_prompt()
                                                     + self.s.fill(REPORT_RULE)), timeout=120)
        out = (getattr(resp, "completion_text", "") or "").strip()
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            raise RuntimeError(f"回答看不懂：{out[:80]}")
        d = json.loads(m.group(0))
        return re.sub(r"&&[^&]*&&", "", str(d.get("say") or "")).strip()[:300]

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
            me = self._me_qq()
            bot_ids = [b for b in (cm.get_bot_self_ids() if cm.get_filter_bot_messages() else []) if str(b) != me]
            msgs = cleaner.clean_messages(raw, bot_self_ids=bot_ids, filter_commands=True)
            limit = max(100, int(cm.get_max_messages() or 1000))
            if len(msgs) > limit:  # 太多就整天均勻抽，別隻剩最後幾個小時
                step = len(msgs) / limit
                msgs = [msgs[int(i * step)] for i in range(limit)]
            logger.info(f"[lively_comic] 群 {gid} 第{offset}天：拉到 {len(raw)} 条，用 {len(msgs)} 条")
            if not msgs:
                return {"success": False, "reason": "no_messages"}
            talk: dict[str, list] = {}
            for m in msgs:
                sid = str(getattr(m, "sender_id", "") or "")
                if sid:
                    rec = talk.setdefault(sid, [0, ""])
                    rec[0] += 1
                    rec[1] = rec[1] or str(getattr(m, "sender_card", "") or getattr(m, "sender_name", "") or "")
            # 有人接話的圖先看一眼，寫成「[图片：…]」一起交給群分析插件（10-31：它只看得到字，圖整段沒了）
            skip = {str(b) for b in bot_ids}
            imgs, seer = see.all_images(raw, skip), see.Seer(self)
            descs = seer.known([i[0] for i in imgs])  # 白天看過的
            try:  # 白天沒看到的（剛開機、排隊滿了），有人接話的補看
                descs.update(await seer.describe([i for i in see.pick(raw, skip) if i[0] not in descs]))
            except Exception as e:
                logger.warning(f"[lively_comic] 群 {gid} 取话题前看图没成：{e}")
            logger.info(f"[lively_comic] 群 {gid} 今天 {len(imgs)} 张图，{len(descs)} 张看过")
            legacy = svc.statistics_service._convert_to_legacy_dict(msgs) + see.legacy_images(imgs, descs)
            legacy = self._mark_me(sorted(legacy, key=lambda d: int(d.get("time") or 0)), me)
            self.__dict__.setdefault("_chat", {})[gid] = see.chat_lines(raw, descs, skip)
            async with svc._llm_slot(gid, "comic_manual"):
                topics, _ = await svc.llm_analyzer.analyze_topics(legacy, umo)
        if not topics:
            return {"success": False, "reason": "no_topics"}
        return {"success": True, "topics": topics, "talk": talk}

    def _me_qq(self) -> str:
        bot_qq = getattr(self.s, "bot_qq", None)
        return str((bot_qq() if bot_qq else "") or "")

    def _mark_me(self, legacy: list, me: str) -> list:
        """〈我〉說的那幾條：發送者換成 ME_ID、名字寫〈我〉，別人 @〈我〉、提到〈我〉的 QQ 號也換成 ME_ID。
        認〈我〉只照 QQ 號，不照名字（群裡還有別的「…肥鱼」）"""
        if not me:
            return legacy
        mine = self.s.fill("〈我〉")
        for d in legacy:
            snd = d.get("sender") if isinstance(d, dict) else None
            if isinstance(snd, dict) and str(snd.get("user_id")) == me:
                snd.update(user_id=ME_ID, nickname=mine, card=mine)
            for part in (d.get("message") or []) if isinstance(d, dict) else []:
                data = part.get("data") if isinstance(part, dict) else None
                if isinstance(data, dict) and isinstance(data.get("text"), str) and me in data["text"]:
                    data["text"] = data["text"].replace(me, ME_ID)
        return legacy

    def _named(self, t, calls: dict) -> str:
        """話題描述裡的 [QQ號] 換成稱呼：出場的人用分鏡的稱呼，ME_ID 是〈我〉，別的照這個話題的參與者名字"""
        g = (lambda k: t.get(k) if isinstance(t, dict) else getattr(t, k, None))
        names = dict(zip(map(str, g("contributor_ids") or []), map(str, g("contributors") or [])))
        me = self._me_qq()
        def one(m):
            q = m.group(1)
            if q in (ME_ID, me):
                return self.s.fill("〈我〉")
            return calls.get(q) or names.get(q) or m.group(0)
        return re.sub(r"\[(\w{1,24})\]", one, str(g("detail") or ""))

    async def draw(self, gid: str, offset: int = 0, auto: bool = False, test: bool = False, done_path=None,
                   redo: dict | None = None) -> str:
        """畫一張，存起來，私信主人預覽。返回給主人的說明。test：只畫、存成 comic_test_*，不發給誰、不進待審。
        done_path：重啟前已經畫好、還沒發的那幾張（路徑清單；舊記錄是一個路徑），不重畫（畫一張要扣錢）。
        redo：〈主人〉請〈我〉補畫的 {"due", "origin", "ts"}：照每天那張的做法畫、給她看，看完、改完就發，最晚改到 due"""
        lock = self._lock(gid)
        if lock.locked():
            return f"「{self._gname(gid)}」的群漫画正在画着"
        async with lock:
            handler = self._gda().comic_command_handler
            if not done_path and not handler.config_manager.get_enable_daily_comic():
                return "漫画功能还没开（生图密钥配好后再开）"
            old = self.state["inflight"].get(gid) or {}
            # 重啟前畫好的：話題、分鏡、改過幾次跟著留下（看圖時給她對照、改的次數接著算）
            if isinstance(done_path, str):
                done_path = [done_path] if done_path else []
            keep = {k: old[k] for k in ("topics", "sb", "sbs", "cast", "fixes_used", "fixes", "texts") if k in old} if done_path else {}
            self.state["inflight"][gid] = {"gid": gid, "offset": offset, "ts": int(time.time()), "auto": auto,
                                           "test": test, **keep, **({"paths": list(done_path)} if done_path else {}),
                                           **({"redo": redo} if redo else {})}
            self._save()
            if redo:
                self._redo[gid] = redo
            try:
                msg = await self._draw_locked(handler, gid, offset, auto, test, done_path)
            except asyncio.CancelledError:
                raise  # 重啟打斷的：留著 inflight，重啟後接著畫
            except Exception:
                self.state["inflight"].pop(gid, None)
                self._save()
                raise
            finally:
                self._redo.pop(gid, None)
                self.__dict__.setdefault("_planned", set()).discard(gid)
            self.state["inflight"].pop(gid, None)
            self._save()
            return msg

    def _lock(self, gid: str) -> asyncio.Lock:
        return self._locks.setdefault(gid, asyncio.Lock())

    async def _draw_locked(self, handler, gid: str, offset: int, auto: bool = False, test: bool = False,
                           done_path=None) -> str:
        umo = self.s.group_umo(gid)
        label = self._window(offset)[2]
        if done_path:
            logger.info(f"[lively_comic] 群 {gid} 重启前画好的群漫画还没发，不重画：{done_path}")
            job = self.state["inflight"].get(gid) or {}
            sbs = list(job.get("sbs") or ([job["sb"]] if job.get("sb") else []))
            sbs = (sbs + [None] * len(done_path))[:len(done_path)]
            cast = job.get("cast") or []
            sbs = [self._drop_made_looks(sb, cast) if sb else None for sb in sbs]
            return await self._publish(gid, label, list(done_path), job.get("topics"), sbs, cast)
        self._sb.pop(gid, None)
        async with (self._gen_sem or contextlib.nullcontext()):  # 只限取話題、畫圖這段；看圖、等到點、發不佔名額
            out = await self._generate(handler, gid, offset, auto, test, label, umo)
        if isinstance(out, tuple):  # 每天那張畫好了：給〈我〉看、等到點、發
            return await self._publish(gid, label, *out)
        return out

    async def _generate(self, handler, gid: str, offset: int, auto: bool, test: bool, label: str, umo: str) -> str:
        redo = gid in self._redo
        tries = max(1, int(self.s.get("comic_topic_tries", 3) or 1)) if auto or redo else 1
        draw_by = self._draw_by_ts() if auto else None  # 第一段（取話題）最晚到這時候，之後要開始畫第一張
        tried = 0
        for i in range(tries):
            err = ""
            tried = i + 1
            try:
                result = await self._topics(handler, gid, offset)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                result, err = {"success": False, "reason": "error"}, str(e)[:120]
            if result.get("success") or result.get("reason") in ("no_messages", "muted"):
                break
            if i + 1 < tries:
                if draw_by and time.time() + TOPIC_RETRY_GAP > draw_by:
                    logger.warning(f"[lively_comic] 群 {gid} 没拿到话题（{err or result.get('reason')}），到了该画第一张的时候，不再试")
                    break
                logger.warning(f"[lively_comic] 群 {gid} 没拿到话题（{err or result.get('reason')}），"
                               f"{TOPIC_RETRY_GAP} 秒后再试（第 {i + 1}/{tries} 次）")
                await asyncio.sleep(TOPIC_RETRY_GAP)
        if not result.get("success"):
            reason = {"no_messages": f"{label}群里没什么消息", "muted": self.s.fill("〈我〉在群里被禁言了"),
                      "no_topics": f"群分析插件取了 {tried} 次都没给出话题",
                      "error": f"取话题出错了（{err}）"}.get(result.get("reason"), str(result.get("reason")))
            self._log("skip", group=gid, reason=reason, offset=offset, day=self._day_of(offset), **({"redo": True} if redo else {}))
            if redo:
                self._redo_refund(gid)
            return f"{label}「{self._gname(gid)}」的群漫画没画成：{reason}"
        items, sb_err, cast = [], "", []
        until = None if test else self._post_ts(gid)  # 畫圖那步失敗，到這時候前來得及就再畫
        for attempt in range(2):  # 分鏡寫壞了（重寫過一次還是壞）：離該畫第一張還早就整個再寫一次；沒有群分析插件那條退路了（11-02）
            try:
                items, cast = await asyncio.wait_for(self._my_comic(gid, result.get("topics", []), result.get("talk") or {}, until),
                                                     timeout=max(900, (until or 0) - time.time()))
                break
            except Exception as e:
                sb_err = str(e) or type(e).__name__
                items = []
                logger.warning(f"[lively_comic] 自己的分镜没画成：{e}")
                self._log("storyboard_fail", group=gid, error=str(e)[:300])
                draw_by = self._draw_by_ts() if auto else None
                if not (isinstance(e, StoryboardBad) and attempt == 0 and draw_by and time.time() + TOPIC_RETRY_GAP < draw_by):
                    break
                await asyncio.sleep(TOPIC_RETRY_GAP)
        if not items:
            if isinstance(sb_err, str) and sb_err.startswith(STORYBOARD_BAD):
                why = f"〈我〉的分镜写坏了，重写了一次还是不行（{sb_err[len(STORYBOARD_BAD):][:80]}），没有别的办法画，这个群这次没有群漫画"
            else:
                why = f"〈我〉的分镜或者画图那步失败了：{comic_fail_reason(sb_err)[0]}"
            self._log("fail", group=gid, day=self._day_of(offset), why=why, error=sb_err[:300], **({"redo": True} if redo else {}))
            if redo:
                self._redo_refund(gid)
            return f"{label}「{self._gname(gid)}」的群漫画没画成：{why}"
        refs, sbs = [], []
        stamp = datetime.now(TZ).strftime('%Y%m%d_%H%M')
        for k, (data, sb) in enumerate(items, 1):
            ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
            tail = f"_{k}" if len(items) > 1 else ""
            path = self.comics_dir / gid / f"comic_{'test_' if test else ''}{gid}_{stamp}{tail}{ext}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            refs.append(str(path))
            sbs.append(sb)
            if not test:
                self.gallery.add(str(path), "群漫画单张", group=gid, day=self._day_of(offset), k=k, n=len(items),
                                 title=str((sb or {}).get("title") or ""),
                                 chat=f"群「{self._gname(gid)}」的群漫画")
        if test:
            self._log("test", group=gid, path=refs[0], paths=refs, offset=offset)
            logger.info(f"[lively_comic] 试画好了：{refs}")
            return "试画好了：" + "、".join(refs)
        # 定時的、補畫的、重啟後接著畫的：一律先給〈我〉看（comic_look），配什麼話、改不改她定（11-02 起沒有「先私信主人預覽」那條路）
        if gid in self.state["inflight"]:  # 看圖、發送時被重啟打斷，重啟後拿這幾張接著，不重畫；話題、分鏡一起留下
            job = self.state["inflight"][gid]
            job["paths"], job["topics"], job["sbs"], job["cast"] = refs, self._topics_lite(result.get("topics")), sbs, cast
            job.pop("path", None)
            self._save()
        return refs, result.get("topics"), sbs, cast

    @staticmethod
    def _image(chain: MessageChain, ref: str) -> MessageChain:
        return chain.url_image(ref) if ref.startswith("http") else chain.file_image(ref)

    # ---------- 發送（10-28） ----------
    async def _deliver(self, gid: str, ref: str, text: str = "") -> str:
        """把一張圖（連同那句話）發到群裡，各群排隊、中間隔 SEND_GAP 秒。返回 "sent" 或 "late"，見 _send_checked"""
        lock = self.__dict__.setdefault("_send_lock", asyncio.Lock())
        async with lock:
            try:
                return await self._send_checked(self.s.group_umo(gid), ref, text)
            finally:
                await asyncio.sleep(SEND_GAP)

    async def _send_checked(self, umo: str, ref: str, text: str = "") -> str:
        """把一張圖（連同那句話）發到 umo（群或私聊）：大 PNG 先轉 JPEG。返回 "sent"，或 "late"（NapCat 報超時、
        翻那邊的消息看到其實發到了）。報超時又沒看到就再發一次；真的沒發成拋錯。
        10-28 10:31 主人私聊畫的 3MB 長圖報超時、其實發到了，被當成沒發，lively_comic_post 找不到這張"""
        send_ref = self._light(ref)
        for attempt in range(2):
            t0 = time.time()
            chain = MessageChain()
            if text:
                chain.message(text)
            try:
                await self.context.send_message(umo, self._image(chain, send_ref))
                return "sent"
            except Exception as e:
                if not self._timed_out(e):
                    raise
                logger.warning(f"[lively_comic] 发到 {umo} 报超时，翻一下那边的消息看到了没有：{str(e)[:80]}")
                if await self._landed(umo, t0):
                    logger.info(f"[lively_comic] {umo} 那张其实发到了（QQ 报的超时）")
                    return "late"
                if attempt:
                    raise
                logger.warning(f"[lively_comic] {umo} 里没看到那张，再发一次")
        raise RuntimeError("没发出去")

    @staticmethod
    def _timed_out(e: Exception) -> bool:
        t = f"{type(e).__name__} {e}"
        return "1200" in t or "Timeout" in t or "timeout" in t or isinstance(e, asyncio.TimeoutError)

    async def _landed(self, where: str, t0: float) -> bool:
        """發送報超時以後：翻那邊最近的消息（where 是群號或 umo，私聊翻和 TA 的），t0 之後有〈我〉發的帶圖的那條就算發到了"""
        client, bot = self.s.client(), str(self.s.bot_qq() or "")
        if client is None or not bot:
            return False
        private = ":FriendMessage:" in where
        tail = where.rsplit(":", 1)[-1]
        action, kw = (("get_friend_msg_history", {"user_id": int(tail)}) if private
                      else ("get_group_msg_history", {"group_id": int(tail)}))
        waited = 0
        for at in SEND_CHECK:
            await asyncio.sleep(max(0, at - waited))
            waited = at
            try:
                res = await client.api.call_action(action, count=20, **kw)
            except Exception as e:
                logger.debug(f"[lively_comic] 翻 {where} 的消息失败：{e}")
                continue
            for m in (res or {}).get("messages") or []:
                if (isinstance(m, dict) and str((m.get("sender") or {}).get("user_id", "")) == bot
                        and float(m.get("time") or 0) >= t0 - 5
                        and any(isinstance(x, dict) and x.get("type") == "image" for x in m.get("message") or [])):
                    return True
        return False

    def _light(self, ref: str) -> str:
        """大 PNG 發之前轉一份 JPEG（原圖留著），轉不了就照原樣發；本來就是 JPEG 的（拼好的大圖）不再壓一次。
        JPEG 的名字帶原圖內容的指紋：形象圖這類固定檔名會被重畫覆蓋，只按檔名認的話會發出上一版
        （10-29 17:20 定做形象重畫，發出去的是 17:11 的舊版，這個缺口從 10-27 就在）"""
        try:
            path = Path(ref)
            if ref.startswith("http") or not path.exists() or path.stat().st_size <= JPEG_OVER or path.suffix.lower() in (".jpg", ".jpeg"):
                return ref
            data = path.read_bytes()
            tag = hashlib.md5(data).hexdigest()[:10]
            sdir = self.dir / "send"  # 只是發 QQ 用的，留在後台、不放她電腦
            out = sdir / f"{path.stem}_{tag}_send.jpg"
            if not out.exists():
                sdir.mkdir(parents=True, exist_ok=True)
                from PIL import Image
                import io
                tmp = out.with_suffix(".tmp")
                with Image.open(io.BytesIO(data)) as im:
                    im.convert("RGB").save(tmp, "JPEG", quality=90, optimize=True)
                tmp.replace(out)  # 寫完才改名，不會發出寫了一半的
                old = re.compile(re.escape(path.stem) + r"(_[0-9a-f]{10})?_send\.jpg")
                for f in sdir.glob(f"{path.stem}_*send.jpg"):  # 同一張圖以前的版本用不到了
                    if f != out and old.fullmatch(f.name):
                        f.unlink(missing_ok=True)
            return str(out)
        except Exception as e:
            logger.warning(f"[lively_comic] 转 JPEG 失败，照原图发：{e}")
            return ref

    def _send_why(self, e: Exception) -> str:
        return ("QQ 那边一直超时，翻群里的消息也没看到" if self._timed_out(e)
                else f"QQ 那边报错：{str(e)[:80] or type(e).__name__}")

    @staticmethod
    def _day_of(offset: int) -> str:
        return (datetime.now(TZ) - timedelta(days=int(offset or 0))).strftime("%Y-%m-%d")

    def _day_record(self, gid: str, day: str) -> dict:
        """events.jsonl 裡這個群那天的群漫畫：{"sent": 定時那張幾點發的, "late", "redo_sent": 補畫發過幾張, "failed": 沒畫成的原因}。
        舊記錄沒寫 day：定時的按發生那天算，補畫的從「昨天（10-27）的群漫画」裡認"""
        rec = {"sent": 0, "late": False, "redo_sent": 0, "failed": ""}
        try:
            lines = self.events_file.read_text("utf-8").splitlines()[-3000:]
        except Exception:
            return rec
        for ln in lines:
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if str(e.get("group")) != gid or e.get("kind") not in ("sent", "fail", "skip", "send_fail"):
                continue
            d = e.get("day")
            if not d:
                m = re.search(r"（(\d\d)-(\d\d)）", str(e.get("what") or ""))
                ts = datetime.fromtimestamp(e.get("ts", 0), TZ)
                d = f"{ts.year}-{m.group(1)}-{m.group(2)}" if m else ("" if e.get("redo") else ts.strftime("%Y-%m-%d"))
            if d != day:
                continue
            if e["kind"] == "sent" and (e.get("auto") or e.get("redo") or "群漫画" in str(e.get("what") or "")):
                if e.get("redo"):
                    rec["redo_sent"] += 1
                elif not rec["sent"]:
                    rec["sent"], rec["late"] = int(e.get("ts", 0)), bool(e.get("late"))
            elif e["kind"] == "fail":
                rec["failed"] = "画图那步失败了" + (f"，{e['why']}" if e.get("why") else "")
            elif e["kind"] == "skip":
                rec["failed"] = str(e.get("reason") or "")
            elif e["kind"] == "send_fail":
                rec["failed"] = "画好了，发到群里没发成"
        return rec

    def _status(self, gid: str) -> str:
        """這個群今天、昨天的群漫畫怎麼樣了，一句話"""
        out = []
        for off in (1, 0):
            day, label = self._day_of(off), {0: "今天", 1: "昨天"}[off]
            r = self._day_record(gid, day)
            h = self.state.setdefault("held", {}).get(gid) or {}
            if h and h.get("day") == day and not r["sent"]:
                out.append(f"{label}的画好存着等〈主人〉看（图册 #{h['page']}），放行用 lively_comic_hold")
                continue
            if r["sent"]:
                t = datetime.fromtimestamp(r["sent"], TZ).strftime("%H:%M")
                out.append(f"{label}的 {t} 发到群里了" + ("（QQ 报了超时，其实发到了）" if r["late"] else ""))
            elif r["failed"]:
                out.append(f"{label}的没发：{r['failed']}")
            elif off == 0:
                continue
            else:
                out.append(f"{label}的没有记录")
            if r["redo_sent"]:
                out[-1] += f"，后来又补画发过 {r['redo_sent']} 张"
        return "；".join(out) or "最近两天没有记录"

    def _redo_board(self, offset: int, starting: str = "") -> str:
        """補畫時各群那天到哪了（10-31 她提的：一起開幾個群時怕轉頭記混，畫重了或漏了）：正在畫的、那天還沒發出去的、發過的。
        starting：剛開的那個群（背景剛起，inflight 可能還沒寫）"""
        day, label = self._day_of(offset), self._window(offset)[2]
        inflight = self.state.get("inflight") or {}
        drawing, waiting, done = [], [], []
        for g in self._groups():
            name = f"「{self._gname(g)}」"
            j = inflight.get(g) or {}
            if g == starting or (j and not j.get("test")):
                off = int(j.get("offset") or 0) if j and g != starting else offset
                drawing.append(name + (f"（{self._window(off)[2]}的）" if off != offset else "")
                               + ("（补画）" if g == starting or j.get("redo") else "（每天定时那张）"))
                continue
            r = self._day_record(g, day)
            hd = self.state.setdefault("held", {}).get(g) or {}
            if hd and hd.get("day") == day:
                waiting.append(name + f"（画好存着等〈主人〉看，图册 #{hd['page']}，放行用 lively_comic_hold）")
                continue
            if r["sent"] or r["redo_sent"]:
                t = datetime.fromtimestamp(r["sent"], TZ).strftime("%H:%M") if r["sent"] else ""
                done.append(name + (f"（{t} 定时那张" if t else "（") + (f"，补画发过 {r['redo_sent']} 张）" if r["redo_sent"] else "）"))
            else:
                waiting.append(name + (f"（{r['failed']}）" if r["failed"] else ""))
        parts = [f"正在画：{'、'.join(drawing)}" if drawing else "正在画：没有",
                 f"{label}还没发出去的：{'、'.join(waiting)}" if waiting else f"{label}各群都发过了",
                 f"{label}发过的：{'、'.join(done)}" if done else ""]
        return f"各群{label}的群漫画——" + "；".join(x for x in parts if x)

    def comic_brief(self) -> str:
        """每天的群漫畫是怎麼來的、今天各群到哪一步了（說到群漫畫時、心跳那頁給她看；不寫群號）"""
        if not self.state.get("enabled", True):
            return "每天的群漫画现在关着（〈主人〉关的），到点不会画"
        groups = self._groups()
        if not groups:
            return "每天的群漫画现在没有开着的群"
        look = "画好会先交给〈我〉看一眼，哪格不对〈我〉可以说怎么改，" if self.s.get("comic_look", True) else ""
        head = (f"每天的群漫画是程序自己画的，不用〈我〉动手，也不是交给谁：{self._start_at()} 开始，"
                f"{len(groups)} 个群（{'、'.join('「' + self._gname(g) + '」' for g in groups)}）各自取当天的话题、"
                f"〈我〉写分镜，从当天的事里挑几件、一件事画一张四格；{look}{self.comic_at} 照顺序发到各自的群里")
        today, now = self._day_of(0), datetime.now(TZ).strftime("%H:%M")
        out = []
        for g in groups:
            r = self._day_record(g, today)
            if r["sent"]:
                st = datetime.fromtimestamp(r["sent"], TZ).strftime("%H:%M") + " 发了"
            elif g in self.state.get("inflight", {}) or (self._locks.get(g) and self._locks[g].locked()):
                st = "正在画"
            elif r["failed"]:
                st = "没画成：" + r["failed"]
            elif now < self._start_at():
                st = "还没开始"
            else:
                st = "还没有记录"
            out.append(f"「{self._gname(g)}」{st}")
        return head + "。今天：" + "；".join(out)

    def _post_ts(self, gid: str = "") -> float | None:
        """今天 comic_at 的時間戳：還沒到、三小時內才算；過了點或格式不對回 None。
        gid 在補畫：最晚改到的時候（還沒到才算）"""
        r = self._redo.get(gid) if gid else None
        if r:
            due = float(r.get("due") or 0)
            return due if due > time.time() else None
        try:
            h, m = (int(x) for x in self.comic_at.split(":"))
        except ValueError:
            return None
        now = datetime.now(TZ)
        at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        left = (at - now).total_seconds()
        return at.timestamp() if 0 < left < 3 * 3600 else None

    def _at(self, gid: str = "") -> str:
        """跟她說幾點發（補畫的是最晚改到幾點）"""
        r = self._redo.get(gid) if gid else None
        return datetime.fromtimestamp(float(r.get("due") or 0), TZ).strftime("%H:%M") if r else self.comic_at

    def _draw_by_ts(self) -> float | None:
        """第二段（畫第一張）最晚幾點開始：發的時間往前 comic_draw_min 分鐘；取話題最晚試到這時候"""
        at = self._post_ts()
        return at - max(0, int(self.s.get("comic_draw_min", 20) or 0)) * 60 if at else None

    async def _wait_post(self, gid: str = ""):
        """每天那張到點前就畫好、看好了（要改的也改完了）：等到 comic_at 再發；補畫的不等"""
        if gid in self._redo:
            return
        at = self._post_ts()
        if at:
            left = at - time.time()
            logger.info(f"[lively_comic] 群漫画画好了，等到 {self.comic_at} 再发（还有 {int(left)} 秒）")
            await asyncio.sleep(max(0, left))

    def _fix_max(self) -> int:
        try:
            return max(0, int(self.s.get("comic_fix_max", 2)))
        except (TypeError, ValueError):
            return 2

    def _fix_secs(self, gid: str, how: str) -> float:
        """估改一次要多久（畫一張＋重畫先改分鏡＋改好再看一遍）：照這個群今天第一張畫了多久"""
        return self._draw_secs.get(gid, DRAW_SECS_GUESS) + (FIX_SB_SECS if how == "重画" else 0) + FIX_LOOK_SECS

    def _fix_note(self, gid: str, ref: str, used: int) -> tuple[str, bool]:
        """看圖時告訴她能不能改、改一次多久、離發還有多久；不能改就照實說為什麼。第二個值：這次能不能改"""
        mx = self._fix_max()
        if mx <= 0:
            return "", False
        when = "看完就" if gid in self._redo else f"到 {self.comic_at} "
        if used >= mx:
            return f"这张已经改了 {used} 次，不能再改了，{when}原样发出去。", False
        at, at_s = self._post_ts(gid), self._at(gid)
        if not at:
            return f"已经过了 {at_s}，这张不改了，看完就发出去。", False
        left, per = at - time.time(), self._fix_secs(gid, "修图")
        has_sb = gid in self._sb
        if ref.startswith("http") and not has_sb:
            return f"这张图不在〈我〉这边，也没留下分镜，改不了，{when}原样发出去。", False
        if left < per:
            return (f"这张来不及改了：离 {at_s} 只剩 {max(0, int(left // 60))} 分钟，改一次要 {-(-int(per) // 60)} 分钟左右，"
                    f"{when}原样发出去。"), False
        until = (f"最晚改到 {at_s}，还有 {int(left // 60)} 分钟" if gid in self._redo
                 else f"离 {at_s} 发还有 {int(left // 60)} 分钟")
        return FIX_NOTE.format(redraw=FIX_REDRAW if has_sb else FIX_NO_REDRAW, per=-(-int(per) // 60),
                               at=at_s, until=until, k=mx - used), True

    async def _publish(self, gid: str, label: str, refs, topics, sbs=None, cast=None) -> str:
        """每天那幾張畫好之後（10-30 起一件事一張）：comic_look 開著就一張一張給〈我〉看，配什麼話、要不要改她定；
        沒看成就照以前直接發。她看了想改（修圖、重畫），到點前來得及就改，改好再給她看一遍、用哪張她定；
        來不及就照原樣（每張各能改 comic_fix_max 次）。到點一定發，照順序一張一張發，每張帶她給那張寫的話。
        直接發群、不私信主人（10-29 用戶定）"""
        name, gumo = self._gname(gid), self.s.group_umo(gid)
        redo = self._redo.get(gid)
        refs = [refs] if isinstance(refs, str) else list(refs)
        if sbs is None and len(refs) == 1 and gid in self._sb:  # 只有一張、分鏡已經放在 _sb 裡（舊的叫法）
            sbs, cast = [self._sb[gid][0]], self._sb[gid][1]
        sbs = (list(sbs or []) + [None] * len(refs))[:len(refs)]
        cast = list(cast or [])
        job = self.state["inflight"].get(gid) or {}
        used_map = job.get("fixes") or {}
        done = []  # 每張：(發哪張, 她看了怎麼說, 改過的, 沒看成的原因)
        strips = self.__dict__.setdefault("_strip", {})
        try:
            for k, ref in enumerate(refs):
                strips[gid] = (k, len(refs), str((sbs[k] or {}).get("title") or ""))
                if sbs[k]:
                    self._sb[gid] = (sbs[k], cast)
                else:
                    self._sb.pop(gid, None)
                used = int(used_map.get(str(k), job.get("fixes_used", 0) if k == 0 else 0) or 0)  # 重啟前已經改過的次數
                done.append(await self._look_fix(gid, label, ref, topics, used))
                sbs[k] = (self._sb.get(gid) or (None,))[0]
        finally:
            strips.pop(gid, None)
        await self._wait_post(gid)
        off = int((self.state["inflight"].get(gid) or {}).get("offset", 0) or 0)
        if self._hold_active(gid):  # 〈主人〉说先看：到发之前的唯一检查点，拼好整页存着不发（11-02）
            return await self._store_held(gid, label, off, done, sbs, redo)
        sent, failed = [], []
        units = [([k], ref, look["text"] if look else "") for k, (ref, look, fixes, err) in enumerate(done)]
        failed_strips = None
        if len(done) > 1:  # 幾張一定拼成一張大圖發（10-30 用戶定；11-02 起拼不了也不一張一張發）
            whole = self._combine(gid, [d[0] for d in done])
            if whole:
                units = [(list(range(len(done))), whole, "\n".join(u[2] for u in units if u[2]))]
            else:  # 拼不起來：這一組當成沒發成，整組留著，lively_comic_post 發的時候再拼一次
                why = f"几张拼不成一张大图（{self.__dict__.get('_combine_why') or '原因不明'}）"
                failed_strips = {"path": done[0][0], "text": "", "why": why, "strips": [d[0] for d in done]}
                units = []
                self._log("send_fail", group=gid, path=done[0][0], day=self._day_of(off), error=why[:300], combine=False,
                          ks=list(range(1, len(done) + 1)), **({"redo": True} if redo else {}))
                logger.error(f"[lively_comic] 群 {gid} 的 {len(done)} 张拼不起来，整组留着没发：{why}")
        if failed_strips:
            failed.append(failed_strips)
        page_id = self._register_page(gid, off, [d[0] for d in done], units[0][1] if units else "", failed_strips and failed_strips["why"])
        for ks, ref, text in units:
            k = ks[0]
            try:
                how_sent = await self._deliver(gid, ref, "")  # 10-31 用戶定：圖先發，話在圖發完之後另外發（_wrap_say）
            except Exception as e:  # 真的沒發成：圖留著，lively_comic_post 能發（10-27 以前沒發成就沒了，她以為圖兩小時就散了）
                failed.append({"path": ref, "text": text, "why": self._send_why(e), **({"n": len(ks)} if len(ks) > 1 else {})})
                if page_id:
                    self.gallery.update(page_id, status="没发成", failed=self._send_why(e))
                self._log("send_fail", group=gid, path=ref, day=self._day_of(off), error=str(e)[:300], k=k + 1,
                          **({"ks": [x + 1 for x in ks]} if len(ks) > 1 else {}), **({"redo": True} if redo else {}))
                logger.error(f"[lively_comic] 群 {gid} 的群漫画{'拼好的大图' if len(ks) > 1 else f'第 {k + 1} 张'}发不出去：{e}")
                continue
            if page_id:
                self.gallery.mark_sent(page_id, f"「{self._gname(gid)}」", late=how_sent == "late", umo=self.s.group_umo(gid))
                for sid in (self.gallery.get(page_id) or {}).get("parent") or []:
                    self.gallery.set_status(sid, "已发")
            for k in ks:
                _, look, fixes, err = done[k]
                own = look["text"] if look else ""
                sent.append((k, own, look, fixes, err))
                self._log("sent", group=gid, path=ref, what=f"{label}的群漫画", auto=not redo, looked=bool(look), pic=page_id or None,
                          day=self._day_of(off), k=k + 1, n=len(done), title=(sbs[k] or {}).get("title", ""),
                          **({"strip": done[k][0]} if len(ks) > 1 else {}),
                          **({"late": True} if how_sent == "late" else {}),
                          **({"redo": True} if redo else {}),
                          **({"text": own, "saw": look["saw"], "why": look["why"]} if look else {}),
                          **({"fixes": fixes} if fixes else {}))
        summary: list[str] = []
        if sent:
            summary = await self._wrap_say(gid, label, [(sbs[k], look) for k, _, look, _, _ in sent])
        if failed:
            first = failed[0]
            self.state["pending"][gid] = {"path": first["path"], "ts": int(time.time()), "offset": off, "label": label,
                                          "day": self._day_of(off), "text": first["text"], "failed": first["why"],
                                          **({"strips": first["strips"]} if first.get("strips") else {}),
                                          **({"more": failed[1:]} if len(failed) > 1 else {})}
        else:
            self.state["pending"].pop(gid, None)
        self._save()
        if sent:
            says = summary
            said = ("，配的话是" + "".join(f"「{t}」" for t in says)) if says else ""
            pics = (f"{len(sent)} 张拼成的一张大图" if len(units) == 1 and len(sent) > 1
                    else f"{len(sent)} 张图" if len(sent) > 1 else "一张图")
            note_outbox(gumo, self.s.fill(f"〈我〉把{label}的群漫画（{pics}）发到群里了{said}"), "群漫画")
            how = "".join(f"，第 {k + 1} 张〈我〉没看成（{err[:60]}），照以前直接发的" for k, _, look, _, err in sent if not look and err)
            fixed = "".join(self._fix_summary(fixes, done[k][0]) for k, _, _, fixes, _ in sent)
            await self._note(f"[〈我〉把{label}「{name}」的群漫画（{pics}）发到群里了{said}{how}{fixed}"
                             f"{'（' + (redo.get('asker') or '〈主人〉') + '请〈我〉补画的）' if redo else '（每日定时）'}]")
            origin = (redo or {}).get("origin")
            if origin and origin not in (gumo, self._owner_umo()):  # 在別的聊天叫她補畫的：那邊也知道發出去了
                note_outbox(origin, self.s.fill(f"{redo.get('asker') or '〈主人〉'}请〈我〉补画的「{name}」{label}的群漫画（{pics}）发到那个群里了{said}"), "群漫画")
        if not failed:
            return "已自动发群"
        part = ("拼好的大图" if failed[0].get("n") else f"这 {len(done)} 张" if failed[0].get("strips")
                else f"{len(done)} 张里有 {len(failed)} 张") if len(done) > 1 else ""
        return (f"{label}「{name}」的群漫画画好了，但是{part}发到群里没发成（{failed[0]['why']}）；图留着（整页是图册 #{page_id}），两天内用 lively_comic_post 写 image=#{page_id} 能发"
                + (f"，〈我〉看图时配的话是「{failed[0]['text']}」" if failed[0]["text"] else ""))

    # ---------- 先看再發（11-02）：〈主人〉說某個群的先給他看，畫好存著，點頭了才發 ----------
    @staticmethod
    def _hold_until(since: float) -> float:
        """「先看」设了以后管到次日（设了之后第一个）06:00：没用上的不拖到隔天，免得把隔天 22:00 该发的那组拦下来（审查 11-02）"""
        d = datetime.fromtimestamp(since, TZ)
        t = d.replace(hour=6, minute=0, second=0, microsecond=0)
        return (t if t > d else t + timedelta(days=1)).timestamp()

    def _hold_active(self, gid: str) -> bool:
        h = self.state.setdefault("hold", {}).get(gid)
        if h and time.time() >= self._hold_until(h.get("since", 0)):
            self.state.setdefault("hold", {}).pop(gid, None)
            return False
        return bool(h)

    async def _store_held(self, gid: str, label: str, off: int, done: list, sbs: list, redo) -> str:
        """這一組畫好、看完（改完）了，不發：拼成整頁（一張就它本身）進圖冊、狀態「等主人看」，存 held；hold 只管一次，這裡就清掉"""
        name = self._gname(gid)
        whole = self._combine(gid, [d[0] for d in done]) if len(done) > 1 else ""
        failed_why = None if (whole or len(done) == 1) else f"几张拼不成一张大图（{self.__dict__.get('_combine_why') or '原因不明'}）"
        page_id = self._register_page(gid, off, [d[0] for d in done], whole or (done[0][0] if len(done) == 1 else ""), failed_why)
        if not page_id:  # 登记不上图册：这组发不了也存不住，别悄悄丢——记错误，当没画成交给 _daily／_redo_run 报给她
            logger.error(f"[lively_comic] 群 {gid} 存着的整页没能进图册，这组没发")
            self._log("held_fail", group=gid, day=self._day_of(off))
            self.state.setdefault("hold", {}).pop(gid, None)
            self._save()
            return f"{label}「{name}」的群漫画画好了，〈主人〉说先看，可是存的时候出错了（整页没能记进图册），这组没发"
        old = (self.state.setdefault("held", {}).get(gid) or {}).get("page")
        if old and old != page_id:  # 重画 again 取代了上一组存着的
            self.gallery.set_status(old, "被重画取代")
        self.gallery.update(page_id, status="等主人看")
        looks = [{"title": str((sbs[k] or {}).get("title") or ""), "saw": (d[1] or {}).get("saw", ""), "text": (d[1] or {}).get("text", ""),
                  "why": (d[1] or {}).get("why", "")} for k, d in enumerate(done)]
        self.state.setdefault("held", {})[gid] = {"page": page_id, "ts": int(time.time()), "day": self._day_of(off), "label": label,
                                   "off": off, "redo": bool(redo), "looks": looks,
                                   **({"asker": redo.get("asker")} if redo and redo.get("asker") else {})}
        self.state.setdefault("hold", {}).pop(gid, None)  # 只管一次：下一组画好存住，hold 就自己清掉
        self.state["pending"].pop(gid, None)
        self._save()
        self._log("held", group=gid, page=page_id, day=self._day_of(off), n=len(done), **({"redo": True} if redo else {}))
        logger.info(f"[lively_comic] 群 {gid} 的{label}群漫画画好了，〈主人〉说先看，存着没发（图册 #{page_id}）")
        facts = (f"「{name}」{label}的群漫画画好了，〈主人〉说先看，存着没发；整页是图册 #{page_id}（{len(done)} 张）。"
                 "要拿给〈主人〉看用 lively_pic（给这里）；〈主人〉点头了在和〈主人〉的私聊里用 lively_comic_hold 放行，说不发了也是同一个工具")
        origin = (redo or {}).get("origin") or ""
        if not (redo and origin == self._owner_umo()):  # 主人私聊里叫她补画的，_redo_run 会在那个聊天叫她一輪
            task = asyncio.create_task(self._wake_owner(facts))
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)
        await self._note(f"[{facts}]")
        return HELD_MSG

    async def _wake_owner(self, facts: str) -> bool:
        """在〈主人〉的私聊給她一輪：有事實要她知道（她說不說、怎麼說自己定）。沒載入自主插件就記進主人私聊的待讀消息"""
        try:
            meta = self.context.get_registered_star("astrbot_plugin_lively_mind")
            mind = meta.star_cls if meta and meta.activated else None
        except Exception:
            mind = None
        owner_umo, owner = self._owner_umo(), self.s.owner()
        ok = False
        if mind is not None and hasattr(mind, "wake_for") and owner:
            ok = await mind.wake_for(owner_umo, owner, self.s.fill(f"后台的事：{facts}"), {"comic_hold": True})
        if not ok:
            note_outbox(owner_umo, self.s.fill(facts), "群漫画")
        return ok

    def _expire_held(self) -> list[str]:
        """存著的超過 HOLD_TTL 還沒放行：不發了，回要告訴她的話"""
        out = []
        now = time.time()
        for gid, h in list((self.state.get("held") or {}).items()):
            if now - h.get("ts", 0) > HOLD_TTL:
                self.state.setdefault("held", {}).pop(gid, None)
                self.gallery.set_status(h.get("page", 0), "存放到期没发")
                out.append(f"「{self._gname(gid)}」{h.get('label', '')}的群漫画（图册 #{h.get('page')}）存着等〈主人〉看，"
                           f"{HOLD_TTL // 3600} 小时过去了一直没放行，到期不发了；图还在图册里，要发还能用 lively_comic_post 写编号")
        for gid, h in list((self.state.get("hold") or {}).items()):
            if now >= self._hold_until(h.get("since", 0)):
                self.state.setdefault("hold", {}).pop(gid, None)
        if out:
            self._save()
        return out

    async def _release_held(self, gid: str) -> str:
        """〈主人〉放行：把存著的整頁發到群裡，每張記 sent，圖發完之後她另外說幾句（_wrap_say，用存著時她看圖寫的）"""
        h = self.state.setdefault("held", {}).get(gid)
        name = self._gname(gid)
        page = self.gallery.get(h["page"]) if h else None
        if not h or not page:
            self.state.setdefault("held", {}).pop(gid, None)
            return f"「{name}」没有存着的群漫画"
        path, why = self._gallery_path(page)
        if not path:
            return f"没发：#{page['id']} {why}；还存着"
        page = self.gallery.get(page["id"]) or page
        try:
            how = await self._deliver(gid, path, "")
        except Exception as e:
            self.gallery.update(page["id"], failed=self._send_why(e))
            return f"没发成：{self._send_why(e)}；还存着，再放行一次会重发"
        self.state.setdefault("held", {}).pop(gid, None)
        self.gallery.mark_sent(page["id"], f"「{name}」", late=how == "late", umo=self.s.group_umo(gid))
        for k, sid in enumerate(page.get("parent") or []):
            self.gallery.set_status(sid, "已发")
            lk = (h.get("looks") or [{}] * (k + 1))[k] if k < len(h.get("looks") or []) else {}
            self._log("sent", group=gid, path=path, what=f"{h.get('label', '')}的群漫画", auto=not h.get("redo"), looked=bool(lk),
                      day=h.get("day"), k=k + 1, n=len(page.get("parent") or []), title=lk.get("title", ""), pic=page["id"], released=True,
                      **({"late": True} if how == "late" else {}), **({"redo": True} if h.get("redo") else {}))
        says = await self._wrap_say(gid, h.get("label", "今天"), [({"title": lk.get("title", "")}, {"saw": lk.get("saw", ""), "text": lk.get("text", "")})
                                                               for lk in h.get("looks") or []])
        said = ("，配的话是" + "".join(f"「{t}」" for t in says)) if says else ""
        note_outbox(self.s.group_umo(gid), self.s.fill(f"〈我〉把{h.get('label', '')}的群漫画（图册 #{page['id']}）发到群里了{said}（〈主人〉点头了）"), "群漫画")
        await self._note(f"[〈我〉把{h.get('label', '')}「{name}」的群漫画（图册 #{page['id']}）发到群里了{said}（〈主人〉点头了）]")
        self._save()
        return f"发了 #{page['id']} 到「{name}」：{self._post_facts(self.gallery.get(page['id']) or page)}{said}"

    @filter.llm_tool("lively_comic_hold")
    async def hold_tool(self, event: AstrMessageEvent, group: str, action: str):
        """〈主人〉说某个群的群漫画先给他看再发、点头了让发、或者说不发了，用这个记下来；这三件事程序只认你在和〈主人〉的私聊里调这个工具，主人在别处（群里）说的、你没调的，程序这边都不知道。
        先看：这个群下一组画好（定时的或者补画的）会存着不发，不用到点；只管一次，存住以后这个设置就自己没了。如果这个群今天的已经发出去了，返回会照实说，设了也拦不住已经发的。
        放行：把存着的这组发到群里（连同图发完之后你另外说的话）；没有存着的，只是把「先看」撤掉。
        不发了：存着的这组不发了（图还在图册里，之后想发还能用 lively_comic_post 写编号），「先看」也撤掉。
        存着的图想拿给〈主人〉看，用 lively_pic。存住以后想改，只能用 lively_comic_redo 写 again 整组重画（重画的这组也先存着，上一组作废）。

        Args:
            group(string): 哪个群：群号或群名里的字
            action(string): 先看、放行、不发了
        """
        if event.unified_msg_origin != self._owner_umo():
            return self.s.fill("没动：这件事只认在和〈主人〉的私聊里调（〈主人〉定的）")
        await self._refresh_names()
        gid, why = self._find_group(str(group or "").strip())
        if not gid:
            return self.s.fill(why)
        name, act = self._gname(gid), str(action or "")
        h = self.state.setdefault("held", {}).get(gid)
        if "不发" in act or "不發" in act or "取消" in act:
            had_hold = self.state.setdefault("hold", {}).pop(gid, None) is not None
            if h:
                self.state.setdefault("held", {}).pop(gid, None)
                self.gallery.set_status(h["page"], "画好")
            self._save()
            return (f"「{name}」不发了：存着的 #{h['page']} 留在图册里（状态：画好），之后想发用 lively_comic_post 写编号" if h
                    else f"「{name}」没有存着的{'；先看的设置撤掉了' if had_hold else ''}")
        if "放" in act or "发" in act or "發" in act:
            self.state.setdefault("hold", {}).pop(gid, None)
            self._save()
            if not h:
                return f"「{name}」没有存着的群漫画；先看的设置已撤掉，之后画好的会照常发"
            return await self._release_held(gid)
        if "看" in act or "先" in act:
            if not self.state["enabled"] or gid in self.state.get("off_groups", []):
                return f"没设：「{name}」的群漫画现在关着"
            day = self._day_of(0)
            rec = self._day_record(gid, day)
            if h:
                return f"「{name}」{h.get('label', '')}的已经画好存着了（图册 #{h['page']}，等你点头），放行或不发了都用这个工具；这次不用再设"
            self.state.setdefault("hold", {})[gid] = {"since": int(time.time())}
            self._save()
            if gid in self.state.get("inflight", {}):
                where = "正在画，画好会存着不发"
            elif rec["sent"]:
                where = (f"今天的 {self._at_ts(rec['sent'])} 已经发到群里了，拦不住那一组；先看只管到明早 6 点，这期间补画（again）的会存着，明晚定时的照常发")
            else:
                where = "今天的还没画好，画好会存着不发"
            return f"设好了：「{name}」下一组群漫画画好先存着不发，等你点头（只管一次，到明早 6 点还没用上就自己撤掉）。{where}。{self._status(gid)}"
        return "不认识这个动作：写 先看、放行 或 不发了"

    def _register_page(self, gid: str, off: int, strip_paths: list, page_path: str, failed_why=None) -> int:
        """這一組的整頁進圖冊（一件事只畫出一張時，那張四格本身就是整頁）；拼不起來的 page_path 空，記 need_combine。回整頁編號"""
        try:
            ids = [(self.gallery.find_path(p, ("群漫画单张", "修图")) or {}).get("id") for p in strip_paths]
            ids = [i for i in ids if i]
            path = page_path or (strip_paths[0] if strip_paths else "")
            if not path:
                return 0
            old = self.gallery.find_path(path, "群漫画整页") if page_path else None
            if old and not failed_why:
                return old["id"]
            titles = [str((self.gallery.get(i) or {}).get("title") or "") for i in ids]
            return self.gallery.add(path, "群漫画整页", group=gid, day=self._day_of(off), n=len(strip_paths), parent=ids,
                                    title="、".join(t for t in titles if t)[:40],
                                    chat=f"群「{self._gname(gid)}」的群漫画", **({"need_combine": True, "status": "没发成", "failed": failed_why}
                                                                           if failed_why else {}))
        except Exception as e:
            logger.warning(f"[lively_comic] 整页没能进图册: {e}")
            return 0

    def _backfill_gallery(self, days: int = 7):
        """第一次上線：把近 7 天「画的图」「群漫画」里已有的圖補進圖冊（11-02）。種類按目錄、檔名猜，提示詞和在哪畫的從 events.jsonl 的記錄對時間配；配不上的空著。
        只做一次（state.gallery_backfill）；補登的整頁只有檔案裡看得出來的（_all.jpg，或一件事只有一張）"""
        if self.state.get("gallery_backfill"):
            return
        self.state["gallery_backfill"] = int(time.time())
        cut = time.time() - days * 86400
        try:
            ev = [json.loads(x) for x in self.events_file.read_text("utf-8").splitlines() if x.strip()] if self.events_file.exists() else []
        except (OSError, ValueError):
            ev = []
        draws = [e for e in ev if e.get("kind") == "draw" and e.get("umo")]
        sents = [e for e in ev if e.get("kind") == "sent" and e.get("path")]
        n = 0
        try:
            for f in sorted(self.drawn_dir.glob("draw_*.png"), key=lambda x: x.stat().st_mtime):
                mt = f.stat().st_mtime
                if mt < cut:
                    continue
                near = min(draws, key=lambda e: abs(e.get("ts", 0) - mt), default=None)
                if near is not None and abs(near.get("ts", 0) - mt) > 180:
                    near = None
                umo = (near or {}).get("umo", "")
                pid = self.gallery.add(str(f), "拍照", ts=mt, where=umo, chat=self._chat_word(umo) if umo else "补登的旧图（不知道在哪个聊天画的）",
                                       prompt=(near or {}).get("prompt", ""), shot=(near or {}).get("shot", ""), look=(near or {}).get("look", ""))
                if near is not None:  # lively_draw 发出去记的是 draw（有 umo、没有 path），不是 sent
                    self.gallery.mark_sent(pid, self._chat_word(umo) if ":GroupMessage:" not in umo else f"「{self._gname(umo.rsplit(':', 1)[-1])}」",
                                           ts=near.get("ts"), umo=umo)
                n += 1
            # 群漫畫：檔名 comic_<群>_<日期_時分>[_<第幾張>][_fix<N>][_all]。修圖、整頁的時間戳是修圖那一刻（整頁名字取自第一張，常常是修過的那張），
            # 所以先按原圖的時間戳成組，修圖掛到「同一群同一天、時間在它之前最近的那組」的第 k 張，_all 掛到時間戳等於某組原圖或某張修圖的那組
            files: dict[tuple, dict] = {}  # (群, 日期) -> {"orig": {stamp: {k: f}}, "fix": [(stamp, k, n, f)], "all": [(stamp, f)]}
            for f in self.comics_dir.glob("*/comic_*"):
                if f.suffix.lower() not in (".png", ".jpg") or f.stat().st_mtime < cut or f.stem.endswith("_send") or "comic_test_" in f.name:
                    continue
                m = re.match(r"comic_(\d+)_(\d{8}_\d{4})(?:_(\d+))?(?:_fix(\d+))?(_all)?$", f.stem)
                if not m:
                    continue
                gid, stamp, k, fix, whole = m.groups()
                d = files.setdefault((gid, stamp[:8]), {"orig": {}, "fix": [], "all": []})
                if whole:
                    d["all"].append((stamp, f))
                elif fix:
                    d["fix"].append((stamp, int(k or 1), int(fix), f))
                else:
                    d["orig"].setdefault(stamp, {})[int(k or 1)] = f
            for (gid, ymd), d in sorted(files.items()):
                day = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                stamps = sorted(d["orig"])
                if not stamps:  # 只有修圖／整頁、原圖已經沒了：認不出是哪一組，不補
                    continue
                grp = {st: {"fix": {}, "stamps": {st}, "all": None} for st in stamps}
                def owner_of(stamp, k=None):
                    before = [st for st in stamps if st <= stamp]
                    if k is not None:
                        has_k = [st for st in before if k in d["orig"][st]]
                        before = has_k or before
                    return before[-1] if before else stamps[0]
                for stamp, k, nfix, f in sorted(d["fix"]):
                    st = owner_of(stamp, k)
                    grp[st]["stamps"].add(stamp)
                    cur = grp[st]["fix"].get(k)
                    if cur is None or (nfix, stamp) >= (cur[0], cur[1]):  # 同一張修了好幾次取最後一次當 final
                        grp[st]["fix"][k] = (nfix, stamp, f)
                for stamp, f in sorted(d["all"]):
                    st = next((s0 for s0 in stamps if stamp in grp[s0]["stamps"]), None) or owner_of(stamp)
                    grp[st]["all"] = f
                for st in stamps:
                    g = grp[st]
                    ids, final = [], []
                    for k in sorted(d["orig"][st]):
                        f = d["orig"][st][k]
                        sid = self.gallery.add(str(f), "群漫画单张", ts=f.stat().st_mtime, group=gid, day=day, k=k, n=len(d["orig"][st]),
                                               chat=f"群「{self._gname(gid)}」的群漫画（补登）")
                        ids.append(sid)
                        fx = g["fix"].get(k)
                        if fx:
                            self.gallery.add(str(fx[2]), "修图", ts=fx[2].stat().st_mtime, group=gid, day=day, k=k,
                                             n=len(d["orig"][st]), parent=sid, chat=f"群「{self._gname(gid)}」的群漫画（补登）")
                        final.append(str(fx[2]) if fx else str(f))
                    page = str(g["all"]) if g["all"] else final[0] if len(final) == 1 else ""
                    if page:
                        hit = next((e for e in sents if e.get("path") in (page, *final)), None)
                        pid = self.gallery.add(page, "群漫画整页", ts=Path(page).stat().st_mtime, group=gid, day=day, n=len(final), parent=ids,
                                               chat=f"群「{self._gname(gid)}」的群漫画（补登）")
                        if hit:
                            self.gallery.mark_sent(pid, f"「{self._gname(gid)}」", ts=hit.get("ts"), late=bool(hit.get("late")),
                                                   umo=self.s.group_umo(gid))
                            for sid in ids:
                                self.gallery.set_status(sid, "已发")
                    n += len(ids)
        except Exception as e:
            logger.warning(f"[lively_comic] 补登旧图进图册没做完: {e}", exc_info=True)
        self._save()
        logger.info(f"[lively_comic] 图册补登了近 {days} 天的 {n} 张旧图")

    async def _wrap_say(self, gid: str, label: str, seen: list) -> list[str]:
        """圖發完之後（10-31 用戶定）：她看完這幾張，另外在群裡說幾句，說幾條、說什麼她定；總結是為了讓人快速了解，
        所以每條很短、最多 WRAP_MAX 條。沒寫成就退回她看圖時的草稿（只取第一句）。回發出去的話"""
        drafts = [(sb or {}).get("title", "") + "：" + (lk or {}).get("saw", "") for sb, lk in seen]
        says: list[str] = []
        try:
            prov = self.s.provider("look_provider_id" if self.s.get("look_provider_id") else "storyboard_provider_id")
            if prov is None:
                raise RuntimeError("没有能用的模型")
            body = "\n".join(f"第 {i + 1} 张：{d}" for i, d in enumerate(drafts))
            drafts_txt = "\n".join(f"第 {i + 1} 张草稿：{(lk or {}).get('text', '')}" for i, (_, lk) in enumerate(seen) if (lk or {}).get("text"))
            resp = await asyncio.wait_for(prov.text_chat(
                prompt=self.s.fill(f"群「{self._gname(gid)}」{label}的群漫画已经发完了，这几张画的是：\n{body}\n{drafts_txt}"),
                system_prompt=self.s.persona_prompt() + WRAP_RULE.format(mx=WRAP_MAX, n=WRAP_LEN)), timeout=120)
            out = (getattr(resp, "completion_text", "") or "").strip()
            m = re.search(r"\{.*\}", out, re.S)
            d = json.loads(m.group(0)) if m else {}
            raw = d.get("say") or []
            raw = [raw] if isinstance(raw, str) else raw
            says = [re.sub(r"&&[^&]*&&", "", str(x)).strip()[:WRAP_LEN * 2] for x in raw if str(x).strip()][:WRAP_MAX]
        except Exception as e:
            logger.warning(f"[lively_comic] 群 {gid} 图发完后的话没写成，退回看图时的草稿：{e}")
            first = next(((lk or {}).get("text") for _, lk in seen if (lk or {}).get("text")), "")
            says = [first] if first else []
        sent_say: list[str] = []
        for t in says:
            try:
                async with self.__dict__.setdefault("_send_lock", asyncio.Lock()):
                    await self.context.send_message(self.s.group_umo(gid), MessageChain().message(t))
                    await asyncio.sleep(2)
                sent_say.append(t)
            except Exception as e:
                logger.warning(f"[lively_comic] 群 {gid} 图后面的话发不出去：{e}")
                break
        self._log("wrap_say", group=gid, said=sent_say)
        return sent_say

    def _combine(self, gid: str, refs: list) -> str:
        """幾張照順序拼成一張大圖，每張原尺寸、不縮小（10-30 用戶定）：兩三張排一行，四張兩行兩列，再多一行三張。
        存成 JPEG，拼不了回空字串、原因記在 self._combine_why（11-02 起拼不了不一張一張發，整組當沒發成留著）"""
        try:
            from PIL import Image
            ims = []
            for r in refs:
                with Image.open(r) as im:
                    ims.append(im.convert("RGB"))
            n = len(ims)
            cols = 2 if n == 4 else min(n, 3)
            rows = -(-n // cols)
            w, h = max(im.width for im in ims), max(im.height for im in ims)
            gap = max(16, w // 32)
            page = Image.new("RGB", (cols * w + (cols + 1) * gap, rows * h + (rows + 1) * gap), "white")
            for i, im in enumerate(ims):
                r, c = divmod(i, cols)
                left = (cols - min(cols, n - r * cols)) * (w + gap) // 2  # 最後一行不滿就放中間
                page.paste(im, (left + gap + c * (w + gap) + (w - im.width) // 2, gap + r * (h + gap) + (h - im.height) // 2))
            out = Path(refs[0]).with_name(re.sub(r"_\d+(_fix\d+)?$", "", Path(refs[0]).stem) + "_all.jpg")
            tmp = out.with_suffix(".tmp")
            page.save(tmp, "JPEG", quality=88, optimize=True)
            tmp.replace(out)
            return str(out)
        except Exception as e:
            logger.warning(f"[lively_comic] 群 {gid} 的几张拼不起来：{e}")
            self._combine_why = (str(e) or type(e).__name__)[:80]
            return ""

    def _strip_k(self, gid: str) -> int:
        """正在看、在改的是這個群今天第幾張（從 0 起）"""
        return int((self.__dict__.get("_strip", {}).get(gid) or (0,))[0])

    async def _look_fix(self, gid: str, label: str, ref: str, topics, used: int):
        """給她看一張，想改就改、改好再看；回 (發哪張, 她最後怎麼說, 改過的, 沒看成的原因)"""
        look, err = None, ""
        fixes: list[dict] = []  # 這次改過的：{"n", "how", "change", "ok", "path"/"why", "secs", "taken"}
        if self.s.get("comic_look", True):
            try:
                look = await self._look(gid, label, ref, topics, *self._fix_note(gid, ref, used))
            except Exception as e:
                err = (str(e) or type(e).__name__)[:200]
                logger.warning(f"[lively_comic] 群 {gid} 的群漫画没看成，照以前直接发：{err}")
                self._log("look_fail", group=gid, path=ref, error=err)
            while look and look["fix"]:
                new = await self._fix(gid, ref, topics, *look["fix"], n=used + len(fixes) + 1, fixes=fixes)
                if not new:  # 沒改成：照原樣發，告訴她為什麼，配的話她照實再寫
                    look = await self._after_fail(gid, label, ref, topics, fixes[-1], look)
                    break
                try:
                    again = await self._look(gid, label, new, topics, *self._fix_note(gid, new, used + len(fixes)),
                                             fixed=fixes[-1])
                except Exception as e:  # 改好的那張沒看成：發她看過的那張
                    logger.warning(f"[lively_comic] 群 {gid} 改好的那张没看成，发原来那张：{e}")
                    self._log("look_fail", group=gid, path=new, error=str(e)[:200], n=fixes[-1]["n"])
                    break
                fixes[-1]["taken"] = again["take"]
                if not again["take"]:  # 她覺得改過的不如原來那張：發原來那張，配的話用她這次寫的
                    logger.info(f"[lively_comic] 群 {gid} 改过的那张她觉得不如原来的：{again['why']}")
                    look = again
                    break
                ref, look = new, again
        return ref, look, fixes, err

    async def _after_fail(self, gid: str, label: str, ref: str, topics, rec: dict, look: dict) -> dict:
        """想改的沒改成：再給她看一眼原來那張，告訴她沒改成、為什麼，配的話她照實再寫；這次也沒看成就用她上次寫的"""
        late = not self._post_ts(gid)
        when = "马上" if late else ("" if gid in self._redo else f"到 {self.comic_at} ")
        note = (f"〈我〉刚才想{rec['how']}：「{rec['change'][:120]}」，没改成（{rec.get('why', '')}）。"
                f"这张就原样{when}发出去。")
        try:
            return await asyncio.wait_for(self._look(gid, label, ref, topics, note, False), timeout=90)
        except Exception as e:
            logger.warning(f"[lively_comic] 群 {gid} 没改成之后再看没看成，用她上次写的话：{e}")
            return look

    @staticmethod
    def _fix_summary(fixes: list[dict], final: str | None) -> str:
        """記進主人私聊的那句後面帶上改過什麼：「（修图「…」改好了；发的是改过的那张）」"""
        if not fixes:
            return ""
        bits = [f"{f['how']}「{f['change'][:40]}」" + (("改好了" if f.get("taken", True) else "改过的不如原来的")
                                                      if f.get("ok") else f"没改成（{f.get('why', '')}）") for f in fixes]
        if any(f.get("path") == final for f in fixes):
            tail = "用的是改过的那张"
        else:
            tail = "用的是原来那张" if any(f.get("ok") for f in fixes) else "照原样"
        return "（〈我〉看了想改：" + "；".join(bits) + "；" + tail + "）"

    async def _fix(self, gid: str, ref: str, topics, how: str, change: str, n: int, fixes: list) -> str:
        """照她說的改一次：來得及、次數沒用完才改；改好回新圖的路徑，沒改成回空串（原因記在 fixes 裡）"""
        rec = {"n": n, "how": how, "change": change[:300]}
        if how == "重画" and gid not in self._sb:
            rec["how"] = how = "修图"  # 沒留下分鏡（群分析插件畫的、重啟前畫的）：照她說的在圖上改
        at, at_s = self._post_ts(gid), self._at(gid)
        need = self._fix_secs(gid, how)
        why = ""
        if n > self._fix_max():
            why = f"这张已经改了 {n - 1} 次"
        elif not at:
            why = f"已经过了 {at_s}"
        elif at - time.time() < need:
            why = f"来不及：离 {at_s} 只剩 {int(at - time.time())} 秒，改一次要 {int(need)} 秒左右"
        elif how == "修图" and ref.startswith("http"):
            why = "这张图不在本地，修不了"
        if why:
            rec.update(ok=False, why=why)
            fixes.append(rec)
            self._log("fix", group=gid, **rec)
            logger.info(f"[lively_comic] 群 {gid} 的群漫画她想{how}（{change[:60]}），没改：{why}")
            return ""
        self._img_take()
        k = self._strip_k(gid)
        if gid in self.state["inflight"]:  # 改一次要畫一張、照樣扣錢：重啟後次數接著算（每張各算各的）
            self.state["inflight"][gid].setdefault("fixes", {})[str(k)] = n
            self._save()
        logger.info(f"[lively_comic] 群 {gid} 的群漫画她想{how}：{change[:80]}")
        t0 = time.time()
        try:
            async with (self._gen_sem or contextlib.nullcontext()):
                path = await asyncio.wait_for(self._fix_draw(gid, ref, topics, how, change, n),
                                              timeout=max(FIX_MIN_WAIT, at - time.time()))
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            path, why = "", f"{at_s} 前没改好"
        except Exception as e:
            path, why = "", f"{draw_fail_reason(str(e))}（{str(e)[:80]}）"
        rec["secs"] = int(time.time() - t0)
        if path:
            rec.update(ok=True, path=path)
            job = self.state["inflight"].get(gid)
            if job is not None:
                paths = job.setdefault("paths", [job.pop("path")] if job.get("path") else [])
                if k < len(paths):
                    paths[k] = path
                if gid in self._sb:
                    sbs = job.setdefault("sbs", [None] * len(paths))
                    if k < len(sbs):
                        sbs[k] = self._sb[gid][0]
                    job["cast"] = self._sb[gid][1]
                self._save()
            logger.info(f"[lively_comic] 群 {gid} 的群漫画{how}好了（{rec['secs']} 秒）：{path}")
        else:
            self._img_back()
            rec.update(ok=False, why=why)
            logger.warning(f"[lively_comic] 群 {gid} 的群漫画{how}没改成：{why}")
        fixes.append(rec)
        self._log("fix", group=gid, **rec)
        return path

    async def _fix_draw(self, gid: str, ref: str, topics, how: str, change: str, n: int) -> str:
        """修圖：把這張交給畫圖模型的 edits 介面，只改她說的；重畫：照她說的先改分鏡，再整張重畫。回新圖的路徑"""
        size = str(self.s.get("comic_size", "1024x1536"))
        if how == "重画":
            sb, cast = self._sb[gid]
            sb2 = (await self._storyboard(topics or [], cast, prev=sb, change=change, gid=gid))[0]
            _, with_me = self._comic_prompt(sb2, cast)
            refs, idx = await self._comic_refs(sb2, cast, with_me)
            prompt, _ = self._comic_prompt(sb2, cast, idx)
            self._log("storyboard", group=gid, panels=len(sb2["panels"]), cast=[c["call"] for c in cast], storyboard=sb2, fix=n)
            data = await self._draw_any(gid, prompt, refs, size, measure=False)
            self._sb[gid] = (sb2, cast)  # 改好那張再看時，給她對照的是改過的分鏡
        else:
            people = await self._fix_people(gid, change)
            prompt = EDIT_PROMPT.format(change=change)
            if people:
                prompt += EDIT_PEOPLE.format(lines="\n".join(f"Image {i}: {en}." for i, (_, en) in enumerate(people, 2)))
            data = await self._draw_any(gid, prompt, [Path(ref)] + [f for f, _ in people], size, measure=False)
        ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
        k = self._strip_k(gid)
        path = self.comics_dir / gid / f"comic_{gid}_{datetime.now(TZ).strftime('%Y%m%d_%H%M')}_{k + 1}_fix{n}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        try:
            par = self.gallery.find_path(ref)
            self.gallery.add(str(path), "修图", group=gid, day=(par or {}).get("day", ""), k=k + 1, n=(par or {}).get("n"),
                             title=(par or {}).get("title", ""), parent=(par or {}).get("id"),
                             chat=f"群「{self._gname(gid)}」的群漫画")
        except Exception as e:
            logger.warning(f"[lively_comic] 修图没能进图册: {e}")
        return str(path)

    async def _fix_people(self, gid: str, change: str) -> list:
        """修圖時她寫到了出場的谁，帶上 TA 的定做形象（沒有就 QQ 頭像）：[(圖, 給畫圖模型的說明)]，最多 EDIT_PEOPLE_MAX 個"""
        ph = getattr(self, "phone", None)
        _, cast = self._sb.get(gid) or (None, [])
        out = []
        for c in cast:
            if len(out) >= EDIT_PEOPLE_MAX:
                break
            if not ph or not c.get("qq") or c.get("no_face") or not any(a in str(change) for a in self._aliases(c)):
                continue
            try:
                got = await ph.person(c["qq"], c["call"])
            except Exception:
                got = None
            if got:
                out.append(got)
        return out

    def _nick(self, qq: str) -> str:
        """TA 的 QQ 暱稱（bond 記的，跟著 QQ 號走，不是群名片）"""
        try:
            meta = self.context.get_registered_star("astrbot_plugin_lively_bond")
            p = meta.star_cls.store.get(str(qq)) if meta and meta.star_cls else None
            return str((p or {}).get("name") or "").strip()
        except Exception:
            return ""

    def _aliases(self, c: dict) -> list[str]:
        """修圖時她寫的是誰：先認 QQ 號，再認這個 QQ 號的 QQ 暱稱（10-29 用戶定：名字牌、群名片會變，不拿來對）"""
        return [a for a in (str(c.get("qq") or ""), self._nick(c.get("qq"))) if a]

    def _qq_by_name(self, name: str) -> str:
        """拍照 refs 裡寫的是名字：只認 QQ 暱稱（和〈主人〉），一模一樣、只對上一個人的才算；認不出回空字串。
        不認群名片、她叫 TA 的（10-29 用戶定：名字會變，先對 QQ 號、再對這個號的暱稱）"""
        name = str(name or "").strip()
        if not name:
            return ""
        if name in (self.s.fill("〈主人〉"), "主人"):
            return str(self.s.owner() or "")
        try:
            meta = self.context.get_registered_star("astrbot_plugin_lively_bond")
            db = meta.star_cls.store.db if meta and meta.star_cls else None
        except Exception:
            db = None
        if db is None:
            return ""
        hits = set()
        try:
            hits |= {str(q) for (q,) in db.execute("SELECT qq FROM people WHERE name=?", (name,))}
        except Exception as e:
            logger.debug(f"[lively_comic] 按名字找人失败: {e}")
            return ""
        return hits.pop() if len(hits) == 1 else ""

    def _made_zh(self, qq: str) -> tuple[bool, str]:
        """TA 有沒有定做的形象、形象的一句中文描述（她自己寫的）"""
        ph = getattr(self, "phone", None)
        try:
            rec = ph.made(str(qq)) if ph else None
        except Exception:
            rec = None
        return (True, made_brief(rec.get("desc", ""))) if rec else (False, "")

    def _look_people(self, sb: dict, cast: list[dict]) -> list[str]:
        """看圖時每個人該是什麼樣子：照定做形象、QQ 頭像畫的照實說（10-28 分鏡給祈瞎編了黑長髮，畫出來照形象是綠髮，
        她看圖時只看到分鏡那句，把對的改成了錯的）；其他人用分鏡寫的樣子"""
        kinds = sb.get("_refs") or {}
        qq_of = {c["call"]: c["qq"] for c in cast if c.get("call")}
        out = []
        for c in sb.get("cast") or []:
            if not isinstance(c, dict) or not str(c.get("称呼") or "").strip():
                continue
            call = str(c["称呼"]).strip()
            made, zh = self._made_zh(qq_of[call]) if call in qq_of else (False, "")
            if call in qq_of:
                nick = self._nick(qq_of[call])
                call = (f"名字牌「{call}」（QQ {qq_of[call]}" + (f"，QQ 昵称「{nick}」" if nick else "")
                        + ("，就是〈主人〉" if self.s.is_owner(qq_of[call]) else "") + "）")
            k = kinds.get(str(c["称呼"]).strip()) or ("made" if made else "")
            if k == "made":
                out.append(f"{call}：照 TA 定做的形象画的" + (f"（{zh}）" if zh else ""))
            elif k == "qq":
                out.append(f"{call}：照 TA 的 QQ 头像画的（头像〈我〉这里看不到）")
            elif c.get("look"):
                out.append(f"{call}：{str(c['look'])[:100]}（分镜里写的，英文）")
        return out

    async def _look(self, gid: str, label: str, ref: str, topics, fix_note: str = "", can_fix: bool = False,
                    fixed: dict | None = None) -> dict:
        """讓〈我〉看畫好的群漫畫：圖連同今天的話題、她寫的分鏡一起給看圖的模型（要認得圖），
        回 {text, why, saw, fix, take}；fix 是 (修图/重画, 改什么) 或 None（告訴過她這次改不了的也是 None）。
        fixed：這張是照她哪次的意見改的；take：看改過的那張時，她要不要用它"""
        pid = "look_provider_id" if self.s.get("look_provider_id") else "storyboard_provider_id"
        prov = self.s.provider(pid)
        if prov is None:
            raise RuntimeError("没有能用的模型")
        lines = [f"群「{self._gname(gid)}」{label}的群漫画。"]
        redo = gid in self._redo
        if fixed:
            lines.append(f"这是改过的一版（今天第 {fixed['n']} 次改）：〈我〉看上一版时要{fixed['how']}——「{fixed['change']}」。"
                         "看看改好了没有：台词、名字牌、名字牌底下那个人的长相和他在做的事对不对得上，别的地方有没有改坏；"
                         "发改过的这张还是原来那张〈我〉定，text 写的是〈我〉选的那张发到群里时的话（不用提改过）。")
        if topics:
            lines.append(f"{label}的话题：")
            for t in topics[:8]:
                g = (lambda k: t.get(k) if isinstance(t, dict) else getattr(t, k, ""))
                cs = g("contributors")
                who = "、".join(map(str, list(cs)[:6])) if isinstance(cs, (list, tuple)) else ""
                lines.append(f"- {g('topic')}" + (f"（{who} 在聊）" if who else "")
                             + f"：{self._named(t, {c['qq']: c['call'] for c in (self._sb.get(gid) or (None, []))[1]})[:120]}")
        sb, cast = self._sb.get(gid) or (None, [])
        if sb:
            lines.append(f"〈我〉画之前写的分镜（{len(sb['panels'])} 格）：")
            for i, p in enumerate(sb["panels"], 1):
                says = "；".join(f"{ln.get('who')}「{ln.get('say')}」" for ln in (p.get("lines") or [])[:3] if isinstance(ln, dict))
                lines.append(f"第 {i} 格「{p.get('caption') or ''}」：谁在 {'、'.join(p.get('who') or [])}"
                             + ("、〈我〉" if p.get("me") else "") + (f"；台词 {says}" if says else ""))
            if cast:
                lines.append("名字牌该写的：" + "、".join(f"{c['call']}（群名片 {c['name']}）" for c in cast))
            looks = self._look_people(sb, cast)
            if looks:
                lines.append("每个人该是什么样子（每格都该一样）：" + "；".join(looks))
                if any("照 TA " in x for x in looks):
                    lines.append("照定做形象、QQ 头像画的人，画出来的样子以形象、头像为准；分镜里给 TA 写的样子是画之前猜的，"
                                 "跟画出来的不一样不算画错")
        elif not topics:
            lines.append("（这张是重启前画好的，话题和分镜没留下）")
        k, n, title = self.__dict__.get("_strip", {}).get(gid) or (0, 1, "")
        strip = ((f"的第 {k + 1} 张（一共 {n} 张，一件事一张）" if n > 1 else "") + (f"，这张画的是「{title}」" if title else ""))
        if n > 1:
            lines.insert(1, f"这次只看第 {k + 1} 张：只核对这一张画的那件事，别的事在另外几张里。")
        intro = (LOOK_INTRO_REDO if redo else LOOK_INTRO).format(name=self._gname(gid), at=self.comic_at, day=label, strip=strip,
                                                               asker=(self._redo.get(gid) or {}).get("asker") or "〈主人〉")
        send = LOOK_HOLD if self._hold_active(gid) else LOOK_SEND_ALL.format(n=n) if n > 1 else LOOK_SEND
        rule = self.s.fill(LOOK_RULE.format(intro=intro, day=label if redo else "今天", fix=fix_note, send=send,
                                            pick=LOOK_PICK if fixed else "", fixf=LOOK_FIX if can_fix else ""))
        img = ref
        if not ref.startswith("http"):  # 縮一下再給模型看，省 token；縮不了就用原圖
            try:
                from PIL import Image
                small = self.dir / f"comic_look_{gid}_{k + 1}.jpg"
                with Image.open(ref) as im:
                    im = im.convert("RGB")
                    im.thumbnail((768, 1152))
                    im.save(small, "JPEG", quality=88)
                img = str(small)
            except Exception as e:
                logger.warning(f"[lively_comic] 缩图失败，用原图看：{e}")
        last = ""
        for _ in range(2):
            resp = await asyncio.wait_for(prov.text_chat(prompt=self.s.fill("\n".join(lines)), image_urls=[img],
                                                         system_prompt=self.s.persona_prompt() + rule), timeout=180)
            out = (getattr(resp, "completion_text", "") or "").strip()
            d = None
            m = re.search(r"\{.*\}", out, re.S) or re.search(r"\{.*", out, re.S)
            for cand in ((m.group(0), m.group(0) + "}") if m else ()):  # 偶爾少了最後那個 }（10-26 重放 1/18）
                try:
                    d = json.loads(cand)
                    break
                except ValueError:
                    pass
            if isinstance(d, dict) and any(k in d for k in ("看到的", "text", "why", "怎么改", "用哪张")):
                text = re.sub(r"&&[^&]*&&", "", str(d.get("text") or "")).strip()[:40]
                how, change = str(d.get("怎么改") or "").strip(), str(d.get("改什么") or "").strip()
                fix = None
                if change and can_fix and how not in ("不改", "不用", "无", "否", "none", "no", "false"):
                    fix = ("重画" if "重" in how else "修图", change[:300])
                return {"text": text, "why": str(d.get("why") or "").strip()[:120],
                        "saw": str(d.get("看到的") or "").strip()[:200],
                        "fix": fix,
                        "take": not (fixed and "原" in str(d.get("用哪张") or ""))}  # 看改過的那張：她要不要用
            last = out[:120]
        raise RuntimeError(f"看图的回答看不懂：{last}")

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
            asyncio.create_task(self._draw_for(d["umo"], d["prompt"], bool(d.get("with_self")), d.get("id"),
                                               text=d.get("text", ""), note=d.get("note", ""), origin=d.get("origin", ""),
                                               shoot={k: d.get(k, "") for k in ("shot", "look", "shape", "refs", "purpose")}))
        todo = []
        for gid, job in list((self.state.get("inflight") or {}).items()):
            if self._lock(gid).locked():
                continue  # 這次開機後這個群已經在畫了，inflight 是它的，不是重啟前留下的
            if job.get("test") or time.time() - job.get("ts", 0) > 3600:  # 試畫被打斷就算了
                self.state["inflight"].pop(gid, None)
                self._save()
                continue
            paths = list(job.get("paths") or ([job["path"]] if job.get("path") else []))
            sbs = (list(job.get("sbs") or ([job["sb"]] if job.get("sb") else [])) + [None] * len(paths))[:len(paths)]
            keep = [(p, sb) for p, sb in zip(paths, sbs) if p and (str(p).startswith("http") or Path(p).exists())]
            done = [p for p, _ in keep]
            if done:
                job["paths"], job["sbs"] = done, [sb for _, sb in keep]
                job.pop("path", None)
                job.pop("sb", None)
                self._save()
            logger.info(f"[lively_comic] 重启前没画完，接着{'发' if done else '画'}：{job}")
            if isinstance(job.get("redo"), dict):  # 主人請她補畫的：照樣看、改到原來說好的時候，看完就發
                todo.append(self._redo_run(gid, int(job.get("offset", 0)), job["redo"], done))
            else:
                todo.append(self._draw_and_report(gid, int(job.get("offset", 0)), True, done))  # 舊記錄 auto=False（以前的先私信主人預覽）11-02 起一律照定時那張接
        if todo:
            await asyncio.gather(*todo)

    async def _loop(self):
        await asyncio.sleep(60)
        try:
            await self._refresh_names()
            self._backfill_gallery()
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
                for fact in self._expire_held():
                    await self._report(fact)
                if self.state["enabled"] and now.strftime("%H:%M") >= self._start_at():
                    due = [g for g in self._groups() if self.state["last_day"].get(g) != day]
                    if due:
                        for gid in due:
                            self.state["last_day"][gid] = day
                        self._save()
                        await self._refresh_names()
                        self._gen_sem = asyncio.Semaphore(max(1, int(self.s.get("comic_parallel", 4) or 1)))
                        logger.info(f"[lively_comic] 开始画今天的群漫画：{len(due)} 个群一起画，{self.comic_at} 发")
                        await asyncio.gather(*(self._daily(gid) for gid in due))
                        self._gen_sem = None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[lively_comic] 定时画漫画失败: {e}", exc_info=True)
            await asyncio.sleep(60)

    def _start_at(self) -> str:
        """每天那輪幾點開始（第一段，取話題）：發的時間往前 comic_prep_min 分鐘；取話題、畫第一張、她看了要改再畫，到點正好發"""
        try:
            at = datetime.strptime(self.comic_at, "%H:%M")
        except ValueError:
            return self.comic_at
        start = at - timedelta(minutes=max(0, int(self.s.get("comic_prep_min", 30) or 0)))
        return start.strftime("%H:%M") if start.day == at.day else "00:00"

    async def _daily(self, gid: str):
        """每天那張，一個群；各群同時跑。沒發成（沒畫成、取不到話題）把事實交給她，跟不跟主人說她定"""
        try:
            msg = await self.draw(gid, 0, True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[lively_comic] 群 {gid} 的群漫画没画成: {e}", exc_info=True)
            msg = f"今天「{self._gname(gid)}」的群漫画没画成：{str(e)[:120]}"
        logger.info(f"[lively_comic] 群 {gid}: {msg}")
        if msg not in DONE_MSGS and not msg.startswith("漫画功能还没开"):
            await self._report(msg)

    def _cleanup_images(self):
        """刪掉超過 keep_image_days 天的圖；還在等審核、剛畫的（狀態裡引用到的）不刪。
        只清後台這邊的（以前放在這裡的、發 QQ 用的 _send.jpg）：群漫畫、畫的圖 10-29 起在她電腦上，是她的東西，
        形象、拍照素材也不能清（以前這裡整個目錄都掃，會把它們也清掉）"""
        cutoff = time.time() - self.keep_days * 86400
        keep = json.dumps(self.state, ensure_ascii=False)
        n = size = 0
        for f in [*self.dir.glob("*"), *(self.dir / "send").glob("*")]:
            try:
                if (f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
                        and f.stat().st_mtime < cutoff and f.name not in keep):
                    size += f.stat().st_size
                    f.unlink()
                    n += 1
            except OSError as e:
                logger.warning(f"[lively_comic] 删旧图失败 {f.name}: {e}")
        for f in (self.dir / "storyboard_bad").glob("*.txt"):  # 壞掉的分鏡原文只留 7 天
            try:
                if f.stat().st_mtime < time.time() - 7 * 86400:
                    f.unlink()
            except OSError:
                pass
        if n:
            logger.info(f"[lively_comic] 清掉 {n} 张超过 {self.keep_days} 天的旧图，腾出 {size / 1048576:.0f}MB")

    # ---------- 擋住會直接發群的工具 ----------
    @filter.on_llm_request(priority=100)
    async def hide_tools(self, event: AstrMessageEvent, req):
        tools = getattr(req, "func_tool", None)
        if not tools:
            return
        hidden = BLOCKED_TOOLS
        qq = str(event.get_sender_id() or "")
        # 轉發剛畫的圖、補畫群漫畫：10-28 起誰那邊都有（以前只給主人），請不請得動、做不做她定
        can_draw = not self._draw_denied(qq)
        if not can_draw:
            hidden = (*hidden, "lively_draw")
        if getattr(event, "unified_msg_origin", "") != self._owner_umo():  # 先看／放行只认〈主人〉私聊里她调
            hidden = (*hidden, "lively_comic_hold")
        if DRAW_ASK_RE.search((event.message_str or "").translate(T2S)):
            try:
                req.extra_user_content_parts.append(
                    TextPart(text=self.s.fill(OWNER_DRAW_HINT if can_draw
                                              else OFF_DRAW_HINT if not self.s.get("draw_chat", True)
                                              else OTHER_DRAW_HINT.format(min=self._draw_min()))).mark_as_temp())
            except Exception:
                pass
        if COMIC_ASK_RE.search((event.message_str or "").translate(T2S)):
            try:
                req.extra_user_content_parts.append(
                    TextPart(text=self.s.fill("[系统提示，不要复述] " + self.comic_brief())).mark_as_temp())
            except Exception:
                pass
        for name in hidden:
            try:
                if tools.get_tool(name):
                    tools.remove_tool(name)
            except Exception:
                pass
        if can_draw:
            self._with_listing(tools)

    def _with_listing(self, tools):
        """lively_draw 的說明後面接上現在有哪些參考素材（素材在資料目錄的 refs.json，改了不用重啟）"""
        try:
            t = tools.get_tool("lively_draw")
        except Exception:
            t = None
        if t is None:
            return
        base = getattr(t, "_lively_base", None)
        if base is None:
            base = str(getattr(t, "description", "") or "")
            try:
                t._lively_base = base
            except Exception:
                return
        listing = self.phone.listing()
        t.description = base + ("\n参考素材（refs 里写名字）：\n" + listing if listing else "")


    # ---------- 主人讓機器人畫畫 ----------
    @filter.llm_tool("lively_draw")
    async def draw_tool(self, event: AstrMessageEvent, prompt: str, with_self: bool = False,
                        to_private: bool = False, text: str = "", shot: str = "", look: str = "", shape: str = "",
                        refs: str = "", purpose: str = ""):
        """用你自己的手机拍一张照片或截一张屏，发到当前聊天（或者 TA 的私聊）。底下是生图模型照你写的生成的，所以你写的是「拍到了什么」。主人和你好感度 70 以上的人才有这个工具。
        拍法（shot）：
        - 自拍：画面里有你，举着手机拍或者对着镜子拍，不用一定看镜头；会自动带上你的参考图
        - 随手拍：你在镜头后面，拍你眼前的东西（碗里的饭、窗外、桌上、你的腿），最多露出你自己的手、腿、脚、尾巴；拍到你自己的部分就在 refs 里带上「我」或者你穿的那套衣服
        - 截图：你手机屏幕上的样子，iPhone（iOS）界面，状态栏是现在的时间；截主屏、锁屏就带上「主屏」「锁屏」
        - 其他：别人想要的其他样子（插画、全身、第三人称、和你无关的画）就照 TA 说的写
        画风（look）：平时是二次元（照你的参考图）；有人想看现实里的你，就写真人，是 cos 你的真人照片，房间也会换成真的房间。
        形状（shape）：方、直（竖着，适合自拍、截图、全身）、横（风景、房间），看需要。
        参考素材（refs）：同一个房间、同一部手机、同一张脸每次拍出来一样，要带哪些写名字（列在说明最后）；画到群友就写 TA 的 QQ 号（最准），或者 TA 的 QQ 昵称（对得上一个人才认；群名片、你叫 TA 的外号不认），先照 TA 定做的形象画，没有才照 QQ 头像；画你自己带「我」。带了参考图的人长相只照图画，prompt 里写的发色、衣服这些不会用。回传会写这次照谁的什么画的、定做的形象长什么样。最多带 10 张。
        画面是照你写的生成的，拍得到谁、拍在哪，跟 TA 这会儿在不在你跟前没关系：拍主人就带上主人那张素材，跟主人合照就把你和主人都带上。
        限制：露骨、裸露的会被审核拒掉；一张大概几十秒到两分钟；一天最多几张（说说配图也算在里面）。画好没画好都会告诉你，画好的图也会放在回传里给你自己看（只你看得到，不会再发给谁）。每张画好的图在图册里有个编号（回传里写着，素材里的「图册.txt」也有），以后要把哪张发到哪个群，用 lively_comic_post 写编号。
        发出去的顺序：这一条回复里写在调用前面的话会先发出去，然后才开始画；text 跟图在同一条里发；工具回来之后你再写的话，会另外再发一条。
        一次调用就是拍一张、发一张；text 只是跟这张图一起发的那句话，不是用来补话的。
        照群里那天的话题画、带名字牌的群漫画是另一个工具 lively_comic_redo。

        Args:
            prompt(string): 拍到了什么，用英文句子写清楚：主体、动作、场景、光线、手机的角度；要在图里写字就把字写进描述。
            shot(string): 自拍、随手拍、截图、其他。
            look(string): 二次元 或 真人，不写就是二次元。
            shape(string): 方、直、横，不写就是方。
            refs(string): 要带的参考素材名字，或者群友的 QQ 号，用逗号隔开；不带就空着。
            purpose(string): 这张图拿来做什么（比如「说说配图」「给 TA 看」），记在图册里方便以后找；不写就空着。
            to_private(boolean): true 就发到 TA 的私聊，不发在当前聊天。
            text(string): 跟图一起发的一句话，不带就只发图。
        """
        qq = str(event.get_sender_id() or "")
        denied = self._draw_denied(qq)
        if denied:
            return f"没画：{denied}"
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        if self.state["draw_day"] != day:
            self.state["draw_day"], self.state["draw_count"] = day, 0
        if self.state["draw_count"] >= self.draw_max:
            return self.s.fill(f"没画：今天已经画了 {self.state['draw_count']} 张，一天最多 {self.draw_max} 张（{DRAW_SHARE}）；"
                               "这一道〈主人〉叫的也算，张数〈主人〉在面板值班页能改" + ASK_OWNER)
        self.state["draw_count"] += 1
        self._save()
        here = event.unified_msg_origin
        umo = self.s.private_umo(qq) if to_private else here
        text = re.sub(r"[ \t]{2,}", " ", LEAK_RE.sub("", str(text or ""))).strip()[:200]
        note = ""
        if umo != here:  # 從別的聊天發過來的：那邊的歷史裡沒有這段，記進待讀消息
            name = event.get_sender_name() or qq
            note = self.s.fill(f"因为{name}在{'群 ' + str(event.get_group_id()) if event.get_group_id() else '别处'}说的"
                               f"「{(event.message_str or '').strip()[:40]}」，〈我〉私聊给 TA 发了一张图（画的是：{prompt[:60]}）"
                               + (f"，配的话是「{text}」" if text else ""))
        shoot = {"shot": str(shot or ""), "look": str(look or ""), "shape": str(shape or ""), "refs": str(refs or ""),
                 "purpose": str(purpose or "")[:40]}
        job = {"id": f"{time.time():.3f}", "umo": umo, "prompt": prompt, "with_self": bool(with_self), "ts": int(time.time()),
               "text": text, "note": note, "origin": here, **shoot}
        self.state["draw_jobs"].append(job)
        self._save()
        self._waiting.add(job["id"])
        task = asyncio.create_task(self._draw_for(umo, prompt, bool(with_self), job["id"], text=text, note=note, origin=here,
                                                  shoot=shoot))
        try:
            res = await asyncio.wait_for(asyncio.shield(task), TOOL_WAIT)
        except asyncio.TimeoutError:
            if not task.done():
                self._waiting.discard(job["id"])  # 之後畫好、畫不成都記進待讀消息，她下一輪看得到
                return "还在画，画好会自动发到这里；没画成的话会记下来，下一轮你能看到"
            res = task.result()
        return self._look_result(res, self._seen.pop(job["id"], ""), DRAW_DONE_NOTE if res.startswith("画好了") else "")

    def _look_result(self, text: str, path: str, tail: str = ""):
        """工具回傳帶上畫好的圖：文字之外多一張縮過的圖，AstrBot 接在下一步給模型（只有她看得到，不再發給誰）。
        讀不出來、這邊沒法帶圖就只回文字"""
        if not path:
            return text + tail
        try:
            import io
            from PIL import Image as PImage
            from mcp.types import CallToolResult, ImageContent, TextContent
            with PImage.open(path) as im:
                size = f"{im.width}x{im.height}"
                im = im.convert("RGB")
                im.thumbnail((SEE_MAX, SEE_MAX))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85)
        except Exception as e:
            logger.warning(f"[lively_comic] 画好的图没能交给她看: {type(e).__name__}: {e}")
            return text + tail
        note = self.s.fill(f"{text}\n画出来的样子在下面（原图 {size}），是给你自己看的，不会再发给谁；已经发出去的就是这张" + tail)
        return CallToolResult(content=[TextContent(type="text", text=note),
                                       ImageContent(type="image", data=base64.b64encode(buf.getvalue()).decode(),
                                                    mimeType="image/jpeg")])

    @filter.on_agent_done(priority=1000001)
    async def looks_out_of_history(self, event: AstrMessageEvent, run_context, resp):
        """給她看過的圖不存進聊天記錄：AstrBot 接的那條帶圖 user 消息拿掉（不然每輪都帶著整張圖、別的插件也會當成這輪的開頭），
        它前面那條工具結果裡的英文換成一句中文。排在 lively_pc 的同類鉤子前面（不然那邊會寫成「看了这张截图」）"""
        try:
            msgs = run_context.messages
            keep = []
            for msg in msgs:
                if msg.role == "user" and isinstance(msg.content, list) and any(
                        str(getattr(p, "text", "") or "").startswith(SEE_MARKS) for p in msg.content):
                    j = len(keep) - 1
                    while j >= 0 and keep[j].role == "tool":
                        if isinstance(keep[j].content, str) and SEE_EN_RE.search(keep[j].content):
                            keep[j].content = SEE_EN_RE.sub(self.s.fill("（〈我〉看了画出来的这张图）"), keep[j].content)
                            break
                        j -= 1
                    continue
                keep.append(msg)
            if len(keep) != len(msgs):
                msgs[:] = keep
        except Exception as e:
            logger.warning(f"[lively_comic] 聊天记录里看过的图没拿掉: {e}")

    def draw_left_note(self) -> str:
        """今天聊天裡還能畫幾張（10-31 她提的：看得見還剩幾張，快用完的時候先知道）"""
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        used = int(self.state.get("draw_count") or 0) if self.state.get("draw_day") == day else 0
        left = max(0, self.draw_max - used)
        tail = "，快用完了" if 0 < left <= DRAW_LOW else ("，用完了，再画会被张数挡住" if left == 0 else "")
        return f"；今天还能画 {left} 张（一天 {self.draw_max} 张，{DRAW_SHARE}）{tail}"

    def take_draw(self) -> bool:
        """算一張進今天畫的張數；到上限了回 False"""
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        if self.state["draw_day"] != day:
            self.state["draw_day"], self.state["draw_count"] = day, 0
        if self.state["draw_count"] >= self.draw_max:
            return False
        self.state["draw_count"] += 1
        self._save()
        return True

    def give_back_draw(self):
        """沒畫成的退回去"""
        self.state["draw_count"] = max(0, int(self.state.get("draw_count", 0)) - 1)
        self._save()

    @filter.llm_tool("lively_avatar")
    async def avatar_tool(self, event: AstrMessageEvent, action: str, desc: str = "", images: str = "", qq: str = "",
                          text: str = "", to_ta: bool = False, group: str = ""):
        """给群友定做 TA 自己的虚拟形象。群漫画、或者别的图画到某个人时，照 TA 定做的形象画；没定做的照 TA 的 QQ 头像画。只能给正在跟你说话的这个人做 TA 自己的，改不了别人的；只有〈主人〉说话的时候例外：主人请你给别人做、你也愿意时，准备、确认都写上 qq，主人的确认就算数（不用 TA 再确认，也不受每人一次的限制），没写新描述、新图就沿用 TA 之前自己准备过的那份。
        分两步：
        - 准备：收 TA 给的参考图（TA 这条带的、这条引用的、TA 半小时内在这个聊天里发的，最多 3 张；也可以不要图）和描述，整理好回你一份摘要。
        - 确认：TA 本人在之后的消息里说确认了，再调这个才真的画（准备的同一条消息里不算，准备后 30 分钟内有效）。画好是一张三视图，发到这个聊天，同一张也会放在回传里给你自己看（只你看得到，不会再发给谁）。
        描述照这个格式写（只写这个人的样子，不写场景、不写别人、不写露骨的）：hair: 发型发色 / eyes: 眼睛 / face: 脸、表情习惯 / body: 身材和年纪感（一律成年）/ outfit: 平时穿的 / accessories: 配件 / features: 特征（耳朵、尾巴、角…）/ vibe: 给人的感觉。怎么问 TA、怎么跟 TA 说由你定。
        每人能做一次；做过的再做要主人同意。主人同没同意由你判断：你觉得主人同意了，在主人说话的聊天里用「放行」写上 TA 的 QQ，程序才记得下（只认主人说话时调的；主人光说一句，程序这边不知道）；放行以后 TA 再准备、确认就会画，主人那边也可以直接替 TA 准备、确认。要先在漫画里画一格 TA、再照它画三视图，大概两三分钟，算进今天画图的张数（两张）；没画成不算次数。
        看：查某人有没有定做的形象；写 group 就列出那个群里所有有形象的人（〈我〉服务的群）。取消：不做了，准备的那份删掉。
        门槛（程序定的）：投喂累计满 ¥50、或者好感度到画图的门槛（draw_min_score），程序会把这件事告诉你，由你决定要不要私信提醒 TA 可以来定做；投喂累计满 ¥150，程序会自动画一张 TA 的形象（没定做的照 QQ 头像）和你的合照，换成 TA 印象卡的专属背景，画好交给你私信发给 TA。TA 有问题可以找〈主人〉。

        Args:
            action(string): 准备、确认、看、取消、放行。
            desc(string): 准备时的描述，照上面的格式。
            images(string): 准备时用哪些图：不写就是 TA 刚发的、引用的；写「不用」就只照描述画。
            qq(string): 看、放行时是谁（QQ 号）；看不写就是正在说话的人。〈主人〉请你替别人准备、确认、取消时写那个人。
            text(string): 确认时写，图画好以后跟图一起发的一句话（确认那会儿不发），不带就只发图。
            to_ta(boolean): 替别人做的，画好后也发到 TA 的私聊（要是 QQ 好友）；不写就只发在这里。
            group(string): 看时写：群号或群名里的字，列出这个群里谁有形象。
        """
        task = asyncio.create_task(self.avatars.run(event, action, desc, images, qq, text, to_ta, group))
        umo = event.unified_msg_origin
        if "确认" not in str(action or ""):
            return self.s.fill(await task)
        try:
            res = self.s.fill(await asyncio.wait_for(asyncio.shield(task), TOOL_WAIT))
            return self._look_result(res, self._seen.pop(umo, ""))
        except asyncio.TimeoutError:
            def done(t: asyncio.Task):
                self._bg.discard(t)
                self._seen.pop(umo, None)  # 工具已經不等了，圖帶不進回傳
                if not t.cancelled():
                    res = t.result() if not t.exception() else "没画成：画图那边出错了"
                    note_outbox(umo, self.s.fill(f"〈我〉给 TA 定做的虚拟形象：{res}"), "画图")
            self._bg.add(task)
            task.add_done_callback(done)
            return "还在画，画好会自动发到这里；没画成的话会记下来，下一轮你能看到"

    def _draw_min(self) -> float:
        try:
            return float(self.s.get("draw_min_score", 70))
        except (TypeError, ValueError):
            return 70.0

    def _draw_denied(self, qq: str) -> str:
        """這個人能不能叫〈我〉畫圖（lively_draw）：主人可以，別人要好感度 ≥ draw_min_score；能就回空串"""
        if not self.s.get("draw_chat", True):
            return "聊天里画图在后台关着"
        if self.s.is_owner(qq):
            return ""
        try:
            meta = self.context.get_registered_star("astrbot_plugin_lively_bond")
            b = getattr(meta, "star_cls", None) if meta else None
            r = b.relation(qq) if b and hasattr(b, "relation") else None
        except Exception:
            r = None
        if r is None:
            return "查不到〈我〉对 TA 的好感度"
        need = self._draw_min()
        if float(r.get("score") or 0) < need:
            return self.s.fill(f"画笔只给〈主人〉和〈我〉好感度 {need:g} 以上的人用，TA 还不到")
        return ""

    def _drawing_providers(self) -> list[dict]:
        d = json.loads(GDA_CONFIG.read_bytes().decode("utf-8-sig"))
        ps = [p for p in d["daily_comic"].get("drawing_provider_overrides", [])
              if p.get("enable", True) and p.get("api_key") and p.get("__template_key") == "openai_images"]
        return sorted(ps, key=lambda p: -int(p.get("priority", 0)))

    # ---------- 面板值班頁的「画图」 ----------
    def draw_brief(self) -> dict:
        """聊天裡畫圖的開關、門檻、張數、用的生圖模型（面板值班頁看、撥）"""
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        try:
            models = [str(p.get("model") or p.get("name") or "") for p in self._drawing_providers()]
        except Exception:
            models = []
        return {"chat": bool(self.s.get("draw_chat", True)), "min": self._draw_min(), "max": self.draw_max,
                "today": self.state["draw_count"] if self.state.get("draw_day") == day else 0, "models": models}

    def set_draw(self, key: str, value) -> tuple[bool, str]:
        """面板改：draw_chat 開關、draw_min_score 好感度門檻、draw_daily_max 每天張數"""
        if key == "draw_chat":
            if not isinstance(value, bool):
                return False, "值不对"
            v, msg = value, f"聊天里画图{'开了' if value else '关了'}"
        elif key == "draw_min_score":
            try:
                v = float(value)
            except (TypeError, ValueError):
                return False, "值不对"
            if not 0 <= v <= 80:
                return False, "好感度门槛要在 0～80 之间"
            msg = f"好感度 {v:g} 以上的人能叫〈我〉画图"
        elif key == "draw_daily_max":
            try:
                v = int(value)
            except (TypeError, ValueError):
                return False, "值不对"
            if not 0 <= v <= 200:
                return False, "每天张数要在 0～200 之间"
            self.draw_max, msg = v, f"每天最多画 {v} 张"
        else:
            return False, "不能改这个"
        try:
            self.s.cfg[key] = v
            self.s.cfg.save_config()
        except Exception as e:
            return False, f"保存失败: {e}"
        return True, msg

    def _job_done(self, job_id: str | None):
        if job_id:
            self.state["draw_jobs"] = [j for j in self.state.get("draw_jobs", []) if j.get("id") != job_id]
            self._save()

    @property
    def gallery(self) -> Gallery:
        g = self.__dict__.get("_gallery")
        if g is None:  # 測試用 __new__ 造的、沒走 __init__
            g = self.__dict__["_gallery"] = Gallery(self.dir, None, self._gname)
        return g

    def _chat_word(self, umo: str) -> str:
        """圖冊裡記「在哪個聊天畫的」的一句話"""
        if umo == self._owner_umo():
            return "〈主人〉私聊"
        if ":GroupMessage:" in umo:
            return f"群聊「{self._gname(umo.rsplit(':', 1)[-1])}」里画的"
        return "别人的私聊里画的"

    def recent_drawn(self, umo: str) -> dict | None:
        """〈我〉在這個聊天兩小時內畫好的最後一張 {"path", "ts", "prompt", "id"}（圖還在的；說說插件配「刚画的」用）。查圖冊"""
        for it in self.gallery.recent(where=umo, kind=("拍照", "说说配图"), limit=6, within=DRAWN_KEEP):
            if Path(it.get("path", "")).exists():
                return {"path": it["path"], "ts": it["ts"], "prompt": it.get("prompt", ""), "id": it["id"]}
        return None

    async def _draw_for(self, umo: str, prompt: str, with_self: bool, job_id: str | None = None,
                        text: str = "", note: str = "", origin: str = "", shoot: dict | None = None) -> str:
        """畫一張發到 umo，回傳結果給工具；工具已經不等了（等太久、重啟後接著畫的）就把結果記進叫她畫的那個聊天（origin）的待讀消息。
        note：從別的聊天發過來時，給 umo 那邊記的一句（那邊的歷史裡沒有起因）"""
        shoot = {} if shoot is None else shoot  # 登記圖冊後把編號寫回 shoot["_id"]
        try:
            ok, why = await self._draw_for_inner(umo, prompt, with_self, text, shoot)
        except asyncio.CancelledError:
            raise  # 重啟打斷的：留著，重啟後接著畫
        except Exception as e:
            logger.error(f"[lively_comic] 画图出错: {e}", exc_info=True)
            ok, why = False, "画图那边出错了"
        self._job_done(job_id)
        if ok and origin and origin != umo and (got := self.recent_drawn(umo)):
            self.gallery.add_where(got["id"], origin)  # 群裡叫的、發到私聊：在叫她畫的那個聊天裡也算「刚画的」
        if ok and note:
            note_outbox(umo, note, "画图")
        where = "TA 的私聊" if note else "这里"
        sent = f"图和你写的「{text}」在同一条里" if text else "只发了图，没带话"
        pid = (shoot or {}).get("_id")
        res = f"画好了{f'（图册 #{pid}）' if pid else ''}，已经发到{where}了（{sent}）{why}{self.draw_left_note()}" if ok else f"没画成：{why}，什么都没发出去"
        if job_id in self._waiting:  # 和上面的 return 之間沒有 await，工具那邊不會在中間放棄等
            self._waiting.discard(job_id)
            if ok and (got := self.recent_drawn(umo)):
                self._seen[job_id] = got["path"]
            return res
        note_outbox(origin or umo, self.s.fill(f"〈我〉给 TA 画的图画好，发到{where}了（画的是：{prompt[:60]}；{sent}）" if ok
                                               else f"〈我〉给 TA 画的那张没画成，什么都没发出去：{why}"), "画图")
        return res

    async def draw_bytes(self, prompt: str, with_self: bool = False) -> bytes:
        """給別的插件用（說說配圖）：照畫圖配置依次試，畫好回傳圖片；全失敗就拋錯。算進今天畫的張數"""
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        if self.state["draw_day"] != day:
            self.state["draw_day"], self.state["draw_count"] = day, 0
        if self.state["draw_count"] >= self.draw_max:
            raise RuntimeError(f"今天已经画了 {self.state['draw_count']} 张，一天最多 {self.draw_max} 张（{DRAW_SHARE}）")
        self.state["draw_count"] += 1
        self._save()
        me_ref = self.me_ref() if with_self else None
        full = ("Xiaofeiyu looks exactly like the reference image; " if me_ref else self.self_look if with_self else "") + prompt
        last_err = "没有可用的画图配置"
        for p in self._drawing_providers():
            try:
                data = await self._call_images(p, full, me_ref)
                pic = 0
                try:  # 11-02：說說配圖也落地到「画的图」、進圖冊（以前只回 bytes，圖冊裡找不到）
                    f = self.drawn_dir / f"draw_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}_qzone.png"
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
                    pic = self.gallery.add(str(f), "说说配图", where="", chat="说说配图（说说插件画的）", purpose="说说配图", prompt=prompt)
                except OSError as e:
                    logger.warning(f"[lively_comic] 说说配图没能存进图册: {e}")
                self._log("draw", umo="", model=p.get("model"), prompt=prompt[:200], with_self=with_self, by="other_plugin",
                          **({"pic": pic} if pic else {}))
                return data
            except Exception as e:
                last_err = f"{p.get('model')}: {e}"
                logger.warning(f"[lively_comic] 画图失败，换下一个：{last_err}")
        self._log("draw_fail", umo="", error=last_err[:300], by="other_plugin")
        raise RuntimeError(last_err)

    async def _draw_for_inner(self, umo: str, prompt: str, with_self: bool, text: str = "",
                              shoot: dict | None = None) -> tuple[bool, str]:
        """照畫圖配置依次試，畫好發到 umo；回傳（成沒成，沒成的原因）。沒成不替她說話，原因交給她。
        shoot：她選的拍法、畫風、形狀、參考素材（手機拍照，10-27）"""
        shoot = {} if shoot is None else shoot
        b = await self.phone.build(prompt, shoot.get("shot", ""), shoot.get("look", ""), shoot.get("shape", ""),
                                   shoot.get("refs", ""), with_self=with_self, call_of=lambda q: self._call_of(q, ""),
                                   qq_of=self._qq_by_name)
        last_err = "没有可用的画图配置"
        data, model = None, ""
        for p in self._drawing_providers():
            try:
                data = await self._call_images(p, b["prompt"], b["refs"], b["size"])
                model = p.get("model")
                break
            except Exception as e:
                last_err = f"{p.get('model')}: {str(e) or type(e).__name__}"
                logger.warning(f"[lively_comic] 画图失败，换下一个：{last_err}")
        if data is None:
            self._log("draw_fail", umo=umo, error=last_err[:300])
            return False, draw_fail_reason(last_err)
        path = self.drawn_dir / f"draw_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        owner = umo == self._owner_umo()
        pic = self.gallery.add(str(path), "拍照", where=umo, chat=self._chat_word(umo), purpose=str(shoot.get("purpose") or "")[:40],
                               prompt=prompt, shot=b["shot"], look=b["look"], shape=shoot.get("shape", ""), refs=",".join(b["used"]))
        shoot["_id"] = pic  # 回傳給她的話帶編號
        self._save()
        try:
            how = await self._send_checked(umo, str(path), text)
        except Exception as e:
            logger.error(f"[lively_comic] 画好的图发不出去：{e}")
            self._log("draw_fail", umo=umo, model=model, error=f"发不出去：{e}"[:300])
            self.gallery.set_status(pic, "没发成")
            return False, (f"图画好了（图册 #{pic}），但是发不出去" + ("（私聊发不过去，可能还不是 QQ 好友）" if ":FriendMessage:" in umo and not owner else "")
                           + ("；图留着" if owner else ""))
        self.gallery.mark_sent(pic, self._chat_word(umo) if ":GroupMessage:" not in umo else f"「{self._gname(umo.rsplit(':', 1)[-1])}」",
                               late=how == "late", umo=umo)
        self._log("draw", umo=umo, model=model, pic=pic, prompt=prompt[:200], with_self=with_self, shot=b["shot"], look=b["look"],
                  size=b["size"], refs=b["used"], missing=b["missing"], **({"late": True} if how == "late" else {}))
        logger.info(f"[lively_comic] 拍好了一张（{b['shot']}，{b['look']}，{b['size']}，参考 {'、'.join(b['used']) or '无'}；{model}）")
        return True, self._people_note(b) + ("" if not b["missing"] else f"（参考素材里没有：{'、'.join(b['missing'])}，没带）")

    def _people_note(self, b: dict) -> str:
        """refs 寫了 QQ 的人照什麼畫的：她聊天時看不到定做形象長什麼樣（10-29 20:56 照形象畫對了金髮，她以為畫錯、說 TA 是藍髮）"""
        out = []
        for x in b.get("people") or []:
            made = x.get("made")
            who = str(x.get("call") or x.get("qq"))
            out.append(f"{who}照 TA 定做的形象画的（{made_brief(made.get('desc', ''))}）" if made and made.get("desc")
                       else f"{who}照 TA 定做的形象画的" if made else f"{who}照 TA 的 QQ 头像画的（头像〈我〉这里看不到）")
        return self.s.fill("（参考图：" + "；".join(out) + "）") if out else ""

    @staticmethod
    def _data_url(f: Path) -> str:
        """參考圖轉成 data URL；太大的（修圖時交的整張漫畫 png）先縮成 jpg"""
        data = f.read_bytes()
        mime = {".png": "image/png", ".webp": "image/webp"}.get(f.suffix.lower(), "image/jpeg")
        if len(data) > 1_500_000:
            try:
                import io
                from PIL import Image
                im = Image.open(io.BytesIO(data)).convert("RGB")
                im.thumbnail((1536, 1536))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=90)
                data, mime = buf.getvalue(), "image/jpeg"
            except Exception:
                pass
        return f"data:{mime};base64," + base64.b64encode(data).decode()

    @classmethod
    async def _call_images(cls, p: dict, prompt: str, refs, size: str = "1024x1024") -> bytes:
        """refs：一張（Path）、好幾張（list）或沒有。帶參考圖走 /images/edits 的 JSON（image_urls 放 data URL，一次能帶好幾張；
        multipart 的 image[0] 那種中轉站回 400），不帶走 generations；都開 stream，不會被中轉站的 Cloudflare 2 分鐘超時掐斷"""
        if isinstance(refs, (str, Path)):
            refs = [Path(refs)]
        refs = [Path(r) for r in refs or [] if r]
        base = str(p["api_url"]).rstrip("/")
        headers = {"Authorization": f"Bearer {p['api_key']}", "User-Agent": "Mozilla/5.0",
                   "Accept": "application/json, text/event-stream"}
        timeout = aiohttp.ClientTimeout(total=int(p.get("timeout") or 300))
        body = {"model": p["model"], "prompt": prompt, "size": size, "n": 1, "stream": True}
        async with aiohttp.ClientSession(timeout=timeout) as s:
            if refs:
                body["image_urls"] = [cls._data_url(r) for r in refs]
                ctx = s.post(f"{base}/images/edits", headers=headers, json=body)
            else:
                ctx = s.post(f"{base}/images/generations", headers=headers, json=body)
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

    # ---------- 自己的分鏡（直式格子、標稱呼） ----------
    def _call_of(self, qq: str, name: str) -> str:
        """〈我〉給 TA 起的稱呼（心裡的 TA 的「称呼」）；沒有就用群名片前四個字。
        主人標群名片（10-25 用戶定：「爹爹」是〈我〉私下的叫法，畫在頭上群友看不懂，還會被畫成長輩）"""
        if self.s.is_owner(qq):
            short = re.sub(r"[^\w\u4e00-\u9fff]", "", name or "")[:8]
            return short or self.s.fill("〈主人〉")
        try:
            meta = self.context.get_registered_star("astrbot_plugin_lively_bond")
            b = getattr(meta, "star_cls", None) if meta else None
            r = b.relation(qq) if b and hasattr(b, "relation") else None
            call = str(((r or {}).get("heart") or {}).get("称呼") or "").strip()
            if call:
                return call[:6]
        except Exception:
            pass
        short = re.sub(r"[^\w\u4e00-\u9fff]", "", name or "")
        return (short or name or qq)[:4]

    def _cast(self, topics, talk: dict) -> list[dict]:
        """今天出場的人：話題裡的參與者在前，再按說話多少補，最多 comic_cast_max 個；不含〈我〉"""
        bot = self.s.bot_qq()
        order: list[str] = []
        for t in topics:
            ids = t.get("contributor_ids") if isinstance(t, dict) else getattr(t, "contributor_ids", [])
            for q in ids or []:
                q = str(q)
                if q and q not in (bot, ME_ID) and q not in order:
                    order.append(q)
        for q, _ in sorted(talk.items(), key=lambda kv: -kv[1][0]):
            if q != bot and q not in order:
                order.append(q)
        out = []
        for q in order[: int(self.s.get("comic_cast_max", 10))]:
            n, name = talk.get(q, [0, ""])
            out.append({"qq": q, "name": name, "call": self._call_of(q, name), "n": n})
        # 撞名的換回群名片：〈我〉叫 XChen446「陈」，主人的群名片也是「陈」，畫出來像同一個人
        taken = {self.s.fill("〈主人〉")}
        taken |= {re.sub(r"[^\w\u4e00-\u9fff]", "", v[1] or "")[:4] for q, v in talk.items() if self.s.is_owner(q)} - {""}
        for c in out:
            if self.s.is_owner(c["qq"]):
                continue
            if c["call"] in taken:
                short = re.sub(r"[^\w\u4e00-\u9fff]", "", c["name"] or "")[:8]
                c["call"] = short if short and short not in taken else c["call"] + "²"
            taken.add(c["call"])
        return out

    @staticmethod
    def _topics_lite(topics) -> list[dict]:
        """話題留一份能存進狀態檔的（重啟後看圖、重畫還要對照）"""
        out = []
        for t in topics or []:
            g = (lambda k: t.get(k) if isinstance(t, dict) else getattr(t, k, None))
            out.append({"topic": str(g("topic") or "")[:100], "detail": str(g("detail") or "")[:300],
                        "contributors": [str(x) for x in (g("contributors") or [])][:10],
                        "contributor_ids": [str(x) for x in (g("contributor_ids") or [])][:10]})
        return out[:10]

    async def _storyboard(self, topics, cast: list[dict], prev: dict | None = None, change: str = "",
                          most: int = 1, why: str = "", chat: list | None = None, gid: str = "") -> list[dict]:
        """寫分鏡：回一件事一張的清單，每張 {"cast", "title", "topic", "panels"}（10-30 起一件事一張四格）。
        most、why：今天最多畫幾件、為什麼是這個數（照實告訴她）。
        prev、change：她看了照 prev 那張畫出來的圖要重畫，照她說的只改這一張，回的清單只有一張"""
        lo, hi = self._panels_range()
        calls = {c["qq"]: c["call"] for c in cast}
        mine = {ME_ID, self._me_qq()}
        me_call = self.s.fill("〈我〉")
        lines = ["今天的话题："] if topics else []
        for t in topics or []:
            g = (lambda k: t.get(k) if isinstance(t, dict) else getattr(t, k, ""))
            who = ([self.s.fill("〈我〉") if str(q) in mine else calls[str(q)] for q in g("contributor_ids") or []
                    if str(q) in calls or str(q) in mine] or list(map(str, g("contributors") or [])))
            lines.append(f"- {g('topic')}（{'、'.join(who)}）：{self._named(t, calls)[:200]}")
            said = see.topic_chat(chat or [], f"{g('topic')} {g('detail')}", {str(q) for q in g("contributor_ids") or []},
                                  lambda q, n: me_call if q in mine else calls.get(q) or n)
            if said:
                lines.append("  相关的原话：\n" + said)
        lines.append("今天出场的人（称呼｜群名片｜说了几条），画谁都用这里的称呼：")
        for c in cast:
            made, zh = self._made_zh(c["qq"])
            lines.append(f"- {c['call']}｜{c['name']}｜{c['n']}" + ("（就是〈主人〉）" if self.s.is_owner(c["qq"]) else "")
                         + ("｜有定做的形象" if made else "") + ("｜头像不是人" if c.get("no_face") else ""))
        if prev:
            prev = self._drop_made_looks(prev, cast)
            lines.append("〈我〉上一版这一张的分镜：" + json.dumps(
                {"cast": prev.get("cast") or [], "strips": [{k: prev.get(k) for k in ("title", "topic", "panels")}]},
                ensure_ascii=False))
            lines.append(f"〈我〉看了照这份分镜画出来的图，要重画，要改的是：{change}")
            lines.append("照这个改一份新的分镜（格式跟上面说的一样），没提到的格子和人的样子尽量照旧")
            most = 1
        prov = self.s.provider("storyboard_provider_id")
        if prov is None:
            raise RuntimeError("没有能用的模型")
        rule = self.s.fill(STORYBOARD_RULE.format(lo=lo, hi=hi, most=max(1, most), why=why or "今天能画的张数")
                           + (STORYBOARD_ONE.format(lo=lo, hi=hi) if prev else ""))
        if chat is not None:  # 交給分鏡的話題和原話留一份，查畫錯時看她當時拿到什麼
            self._log("storyboard_in", text="\n".join(lines)[:8000])
        resp = await asyncio.wait_for(prov.text_chat(prompt=self.s.fill("\n".join(lines)), system_prompt=self.s.persona_prompt() + rule), timeout=120)
        text = (getattr(resp, "completion_text", "") or "").strip()
        try:
            sb = self._parse_sb(text)
        except ValueError as e:  # 11-02：11-01 22:41 桐群 JSON 在第 3134 字壞了，以前直接退回群分析插件畫長圖。
            # 先本地修（去 ```、尾逗號、缺的逗號、沒收的括號）；修不好再請備用模型（fallback_storyboard_provider_id，換一家比同一個再寫一遍不容易同樣壞）照原樣補成合法 JSON，只重寫 1 次
            self._keep_bad(gid, text, str(e))
            sb = self._parse_sb(text, loose=True, quiet=True)
            if sb is not None:
                self._log("storyboard_repair", how="本地修好", error=str(e)[:200], group=gid)
                logger.warning(f"[lively_comic] 分镜 JSON 写坏了（{str(e)[:80]}），本地修好了")
            else:
                self._log("storyboard_repair", how="请模型重写", error=str(e)[:200], tail=text[-200:], group=gid)
                logger.warning(f"[lively_comic] 分镜 JSON 写坏了且本地修不好，请备用模型重写一次：{str(e)[:120]}")
                try:
                    backup = getattr(prov, "_backup", None) or prov  # 沒設備用就用同一個
                    again = await asyncio.wait_for(backup.text_chat(
                        prompt=STORYBOARD_REPAIR.format(err=str(e)[:200], text=text[:12000]),
                        system_prompt="你只负责把别人写坏的 JSON 修成能解析的 JSON，内容一个字都不改，只输出 JSON。"), timeout=120)
                    again_text = (getattr(again, "completion_text", "") or "").strip()
                    try:
                        sb = self._parse_sb(again_text)
                    except ValueError:
                        self._keep_bad(gid, again_text, "重写后还是坏", tag="rewrite")
                        sb = self._parse_sb(again_text, loose=True)
                except Exception as e2:
                    raise StoryboardBad(f"{STORYBOARD_BAD}{str(e2) or type(e2).__name__}") from e2
        raw = sb.get("strips") if isinstance(sb.get("strips"), list) else [sb]  # 偶爾照舊格式寫成一張
        out = []
        for st in raw:
            if not isinstance(st, dict):
                continue
            panels = [p for p in st.get("panels") or [] if isinstance(p, dict) and str(p.get("scene") or "").strip()]
            if not panels:
                continue
            out.append(self._drop_made_looks({"cast": sb.get("cast") or [], "title": str(st.get("title") or "").strip()[:10],
                                              "topic": str(st.get("topic") or "").strip()[:60], "panels": panels[:hi]}, cast))
        if not out:
            raise RuntimeError("分镜一格都没有")
        return out[:max(1, most)]

    @staticmethod
    def _parse_sb(text: str, loose: bool = False, quiet: bool = False) -> dict | None:
        """分鏡文字 → dict。loose：解析不了就先照 _fix_json 本地修一遍；quiet：還是不行回 None 而不是拋 ValueError。
        修好了也只是「能解析」，格子夠不夠、有沒有 scene 還是由 _storyboard 後面的欄位檢查說了算"""
        try:
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                raise ValueError(f"分镜不是 JSON：{text[:120]}")
            try:
                sb = json.loads(m.group(0))  # JSONDecodeError 是 ValueError
            except ValueError:
                if not loose:
                    raise
                sb = json.loads(fix_json(text))
            if not isinstance(sb, dict):
                raise ValueError("分镜不是一个 JSON 对象")
            return sb
        except ValueError:
            if quiet:
                return None
            raise

    def _keep_bad(self, gid: str, text: str, why: str, tag: str = "bad"):
        """壞掉的分鏡原文整段存一份（storyboard_bad/，留 7 天），下次再壞能查根因（11-01 那次沒存，根因查不出來）"""
        try:
            d = self.dir / "storyboard_bad"
            d.mkdir(exist_ok=True)
            (d / f"{gid or 'x'}_{datetime.now(TZ).strftime('%m%d_%H%M%S')}_{tag}.txt").write_text(f"# {why}\n{text}", "utf-8")
        except OSError as e:
            logger.warning(f"[lively_comic] 存坏掉的分镜原文失败：{e}")

    def _panels_range(self) -> tuple[int, int]:
        """一張幾格：預設 3～4（10-30 用戶定）"""
        try:
            lo, hi = int(self.s.get("comic_panels_min", 3)), int(self.s.get("comic_panels_max", 4))
        except (TypeError, ValueError):
            lo, hi = 3, 4
        hi = max(1, hi)
        return max(1, min(lo, hi)), hi

    def _drop_made_looks(self, sb: dict, cast: list[dict]) -> dict:
        """有定做形象的人，分鏡 look 一律清空：長相只照形象圖畫（10-29 用戶定）；以前存下的分鏡（重畫時沿用的 prev）也一樣"""
        made = {c["call"] for c in cast if c.get("call") and self._made_zh(c["qq"])[0]}
        for c in sb.get("cast") or []:
            if isinstance(c, dict) and str(c.get("称呼") or "").strip() in made:
                c["look"] = ""
        return sb

    async def _comic_refs(self, sb: dict, cast: list[dict], with_me: bool) -> tuple[list[Path], dict]:
        """群漫畫帶哪些參考圖：畫到〈我〉帶她的參考圖；出場的人帶 TA 定做的形象，沒有就帶 QQ 頭像（10-27 用戶定）。
        回（圖，{稱呼: (第幾張, 給模型的說明)}；〈我〉的鍵是空字串）；一張最多 MAX_REFS 張，多的人不帶。
        誰照定做形象、誰照 QQ 頭像畫的記在 sb["_refs"]（made／qq），看圖時照實告訴她"""
        refs, idx, kinds = [], {}, {}
        me_ref = self.me_ref()
        if with_me and me_ref:
            refs.append(me_ref)
            idx[""] = (1, "Xiaofeiyu, the main girl")
        calls = self._in_strip(sb)
        for c in cast:
            if c["call"] not in calls or len(refs) >= MAX_REFS or c.get("no_face"):
                continue
            try:
                got = await self.phone.person(c["qq"], c["call"])
            except Exception:
                got = None
            if got:
                refs.append(got[0])
                idx[c["call"]] = (len(refs), got[1])
                kinds[c["call"]] = "made" if self._made_zh(c["qq"])[0] else "qq"
        sb["_refs"] = kinds
        return refs, idx

    @staticmethod
    def _in_strip(sb: dict) -> set:
        """這張真的畫到的人（分鏡 cast 是幾張共用的，沒出場的不帶參考圖、不列，免得畫圖模型把長得像的人混在一起）"""
        cast = {str(c.get("称呼") or "").strip() for c in sb.get("cast") or [] if isinstance(c, dict)}
        seen = {str(w) for p in sb.get("panels") or [] for w in (p.get("who") or [])}
        seen |= {str(ln.get("who")) for p in sb.get("panels") or [] for ln in (p.get("lines") or []) if isinstance(ln, dict)}
        return {c for c in cast if c and c in seen}

    def _comic_prompt(self, sb: dict, cast: list[dict], idx: dict | None = None) -> tuple[str, bool]:
        """分鏡 → 給畫圖模型的英文提示詞；第二個值：有沒有畫〈我〉（有就帶參考圖）。
        idx：_comic_refs 給的參考圖編號（帶了誰的頭像），有就在開頭列出、每個人照那張畫"""
        me = self.s.fill("〈我〉")
        calls = {c["call"] for c in cast}
        owner_call = next((c["call"] for c in cast if self.s.is_owner(c["qq"])), None)
        owner_look = str(self.s.get("comic_owner_look", "") or "").strip()
        panels = sb["panels"]
        with_me = any(p.get("me") or me in (p.get("who") or []) for p in panels)
        idx = idx or {}
        out = []
        if idx:
            out.append("Reference images, in order:")
            out += [f"Image {i}: {en}." for i, en in sorted(idx.values())]
            out.append("Turn every reference into the same cute chibi comic style; do not copy any text from the references. "
                       "Anyone who has a reference image gets their looks (hair, eyes, clothes, accessories) only from it; "
                       "ignore any looks written for them below.")
        out.append(f"A vertical comic page (portrait), {COMIC_LAYOUT.format(n=len(panels))}, "
                   "clean panel borders with white gutters, cute chibi anime style, soft pastel colors, warm and funny mood.")
        if str(sb.get("title") or "").strip():
            out.append(f"Title at the top with exact Chinese text \"{str(sb['title'])[:10]}\".")
        if self.s.get("comic_vertical_bubbles", True):
            out.append("Speech bubbles are tall and narrow, with the Chinese text written vertically (top to bottom).")
        out.append("Characters (how each one looks, the same wherever they appear; "
                   "a character is drawn ONLY in the panels that list them, never as a background extra):")
        if with_me:
            out.append("- Xiaofeiyu (the main girl): " + (f"looks like image {idx[''][0]}" if "" in idx
                                                           else self.self_look.strip() or "a cute chibi whale girl")
                       + "; NO name tag above her head (she is recognised by her looks)")  # 10-30 用戶定：她的名字牌老寫錯字，不給
        shown = self._in_strip(sb)
        for c in sb.get("cast") or []:
            if isinstance(c, dict) and str(c.get("称呼") or "").strip() in calls & shown:
                look = owner_look if owner_look and c["称呼"] == owner_call else str(c.get("look") or "simple casual look")
                if c["称呼"] in idx:
                    look = f"looks like image {idx[c['称呼']][0]}"
                out.append(f"- {c['称呼']}: young chibi person, {look[:120]}; "
                           f"a small rounded name tag above the head with exact Chinese text \"{c['称呼']}\"")
        for i, p in enumerate(panels, 1):
            bits = [f"Panel {i}: {str(p['scene'])[:400]}"]
            who = [w for w in (p.get("who") or []) if w in calls]
            if who:
                bits.append("In this panel: " + ", ".join(who) + ", each with their name tag"
                            + (", and Xiaofeiyu (no name tag)." if p.get("me") else ".") + PANEL_ONLY)
            elif p.get("me"):
                bits.append("In this panel: Xiaofeiyu (no name tag)." + PANEL_ONLY)
            for ln in (p.get("lines") or [])[:3]:
                if isinstance(ln, dict) and str(ln.get("say") or "").strip():
                    speaker = "Xiaofeiyu" if ln.get("who") == me else str(ln.get("who") or "")
                    bits.append(f"{speaker} has a speech bubble with exact Chinese text \"{str(ln['say'])[:15]}\".")
            if str(p.get("caption") or "").strip():
                bits.append(f"A small handwritten side note at the edge of the panel with exact Chinese text \"{str(p['caption'])[:12]}\".")
            out.append(" ".join(bits))
        out.append("STRICT: render ONLY the exact Chinese text given for the title, name tags, speech bubbles and side notes; no other text, "
                   "no numbers, no QQ IDs, no English words on the image. Not photorealistic. "
                   + "Each panel shows only the people named for that panel. "
                   + ("People who look alike are still different people: draw each one from their own reference image, "
                      "keeping its headwear and props in every panel. " if idx else "")
                   + ("Xiaofeiyu has NO name tag. Xiaofeiyu has exactly ONE whale tail and whale-fin ears (no human ears), no horns, no wings." if with_me else ""))
        return "\n".join(out), with_me

    # ---------- 每天群漫畫畫了幾張：只記數（10-31 用戶定：群漫畫不算進每天的張數上限；試畫不記） ----------
    def _img_used(self) -> int:
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        if self.state.get("img_day") != day:
            self.state["img_day"], self.state["img_n"] = day, 0
        return int(self.state.get("img_n") or 0)

    def _img_take(self, gid: str = ""):
        if gid and ((self.state.get("inflight") or {}).get(gid) or {}).get("test"):
            return
        self.state["img_n"] = self._img_used() + 1
        self._save()

    def _img_back(self, gid: str = ""):
        """沒畫出來的那張不算"""
        if gid and ((self.state.get("inflight") or {}).get(gid) or {}).get("test"):
            return
        if self._img_used() > 0:
            self.state["img_n"] -= 1
            self._save()

    def _strips_most(self, gid: str) -> tuple[int, str]:
        """這個群今天最多畫幾件事、為什麼（照實告訴她）：不超過 comic_strips_max，還要趕得上到點"""
        try:
            cap = max(1, int(self.s.get("comic_strips_max", 6)))
        except (TypeError, ValueError):
            cap = 6
        mins = -(-int(self._draw_secs.get(gid, DRAW_SECS_GUESS)) // 60)
        why = f"一个群最多画 {cap} 件；一张大约画 {mins} 分钟，画几张都得在 {self._at(gid)} 前画完、看完"
        return cap, why

    async def _my_comic(self, gid: str, topics, talk: dict, until: float | None = None) -> tuple[list[tuple[bytes, dict]], list[dict]]:
        """寫分鏡、一件事畫一張；回 ([(圖, 那張的分鏡)], 出場的人)。有幾張沒畫成就跳過，一張都沒畫成才拋錯"""
        cast = self._cast(topics, talk)
        await self._judge_faces(cast)
        most, why = self._strips_most(gid)
        sbs = await self._storyboard(topics, cast, most=most, why=why, chat=self.__dict__.get("_chat", {}).get(gid), gid=gid)
        self.__dict__.setdefault("_planned", set()).add(gid)
        size = str(self.s.get("comic_size", "1024x1536"))
        async def one(k: int, sb: dict):
            self._img_take(gid)
            try:
                return await self._draw_strip(gid, sb, cast, size, until, k, len(sbs)), sb
            except Exception as e:
                self._img_back(gid)
                logger.warning(f"[lively_comic] 群 {gid} 第 {k} 张（{sb.get('title')}）没画成，跳过：{str(e)[:120]}")
                self._log("strip_fail", group=gid, k=k, title=sb.get("title"), error=str(e)[:300])
                return e
        # 10-31 起幾張一起畫（同時幾張由 _draw_any 的通道管），發的時候照分鏡的順序
        res = await asyncio.gather(*(one(k, sb) for k, sb in enumerate(sbs, 1)))
        out = [r for r in res if isinstance(r, tuple)]
        last = next((r for r in res if isinstance(r, Exception)), None)
        if not out:
            raise last or RuntimeError("一张都没画成")
        return out, cast

    async def _judge_faces(self, cast: list[dict]):
        """QQ 頭像裡沒有能照著畫的人的（風景、寵物、logo），標 no_face：不帶頭像，照分鏡寫的樣子畫（10-31 用戶定）。
        定做過形象的不判斷；問不到就照舊帶頭像"""
        ph = getattr(self, "phone", None)
        if not ph or not hasattr(ph, "has_face"):
            return
        async def one(c):
            try:
                if await ph.has_face(c["qq"]) is False:
                    c["no_face"] = True
            except Exception as e:
                logger.warning(f"[lively_comic] 看 {c.get('call')} 的头像是不是人没成：{e}")
        await asyncio.gather(*(one(c) for c in cast if c.get("qq")))

    async def _draw_strip(self, gid: str, sb: dict, cast: list[dict], size: str, until: float | None, k: int, n: int) -> bytes:
        _, with_me = self._comic_prompt(sb, cast)
        refs, idx = await self._comic_refs(sb, cast, with_me)
        prompt, _ = self._comic_prompt(sb, cast, idx)
        self._log("storyboard", group=gid, panels=len(sb["panels"]), cast=[c["call"] for c in cast], storyboard=sb,
                  refs=[k2 or "〈我〉" for k2 in idx], k=k, n=n,
                  prompt=prompt, ref_files=[str(r) for r in refs])  # 原樣留著：換模型比較、查畫錯時照這份重畫
        for t in range(DRAW_RETRIES + 1):
            try:
                data = await self._draw_any(gid, prompt, refs, size)
                break
            except Exception as e:
                # 10-27 21:22 小凛群兩個模型都報錯（五個群一起畫），之後就沒畫了；那時離發還有半小時以上
                # 審核拒了、參考圖讀不了：再畫多半一樣，不等（10-28 另一個 session 轉來的建議）
                if (not until or t >= DRAW_RETRIES or not comic_fail_reason(str(e))[1]
                        or time.time() + DRAW_RETRY_GAP + DRAW_SECS_GUESS > until):
                    raise
                logger.warning(f"[lively_comic] 群 {gid} 第 {k} 张画图那步没成（{str(e)[:80]}），{DRAW_RETRY_GAP} 秒后再画（第 {t + 1}/{DRAW_RETRIES} 次）")
                self._log("draw_retry", group=gid, error=str(e)[:200], n=t + 1, k=k)
                await asyncio.sleep(DRAW_RETRY_GAP)
        logger.info(f"[lively_comic] 群 {gid} 的漫画第 {k}/{n} 张画好了：「{sb.get('title')}」{len(sb['panels'])} 格"
                    f"（{size}，{int(self._draw_secs.get(gid, 0))} 秒）")
        return data

    async def _draw_any(self, gid: str, prompt: str, ref, size: str, measure: bool = True) -> bytes:
        """照畫圖配置依次試，畫好回傳圖片；全失敗就拋錯。measure：記下這個群這張畫了多久（估改一次來不來得及）"""
        errs: list[str] = []
        t0 = time.time()
        lanes = self._draw_lanes()
        if not lanes:
            raise RuntimeError("没有可用的画图配置")
        # 10-31 用戶疑心同一把 key 同時太多張會卡超時：每把 key 一條通道，一條通道同時最多 comic_lane_max 張，
        # 挑最空的那條；都滿了就等。通道裡照舊先 gpt-image-2.5、不行換 flare（同一把 key）
        busy = self.__dict__.setdefault("_lane_busy", {})
        cap = max(1, int(self.s.get("comic_lane_max", 3) or 3))
        while True:
            free = [(busy.get(i, 0), i) for i in range(len(lanes)) if busy.get(i, 0) < cap]
            if free:
                i = min(free)[1]
                break
            await asyncio.sleep(1)
        busy[i] = busy.get(i, 0) + 1
        try:
            for p in lanes[i]:
                try:
                    data = await self._call_images(p, prompt, ref, size)
                    if measure:
                        self._draw_secs[gid] = time.time() - t0
                    logger.info(f"[lively_comic] 群 {gid} 画好一张（{p.get('model')}" + (f"，通道{i + 1}" if len(lanes) > 1 else "") + "）")
                    return data
                except Exception as e:
                    errs.append(f"{p.get('model')}: {str(e) or type(e).__name__}")
                    logger.warning(f"[lively_comic] 画漫画失败，换下一个：{errs[-1]}" + (f"（通道{i + 1}）" if len(lanes) > 1 else ""))
        finally:
            busy[i] -= 1
        raise RuntimeError("；".join(errs) or "没有可用的画图配置")

    def _draw_lanes(self) -> list[list[dict]]:
        """畫群漫畫的通道：第一條是群分析插件設定裡的那幾個（照優先順序）；資料目錄 draw_keys.json 裡另外加的 key（10-31，
        用 server/mac/set_draw_keys.py 存）每把一條，模型、順序照第一條，只換網址和 key"""
        base = self._drawing_providers()
        lanes = [base] if base else []
        f = self.dir / "draw_keys.json"
        try:
            extra = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        except Exception as e:
            logger.warning(f"[lively_comic] draw_keys.json 读不了，只用原来那把：{e}")
            extra = []
        for x in extra if base else []:
            if isinstance(x, dict) and x.get("api_key"):
                lanes.append([dict(p, api_url=x.get("api_url") or p.get("api_url"), api_key=x["api_key"],
                                   name=f"{x.get('name') or '通道'}-{p.get('model')}") for p in base])
        return lanes

    # ---------- 主人指令 ----------
    def _one_pending(self) -> str | None:
        now = time.time()
        for gid, p in list(self.state["pending"].items()):
            if now - p.get("ts", 0) > PENDING_TTL:
                self.state["pending"].pop(gid, None)
        return next(iter(self.state["pending"]), None)

    async def _send_to(self, gid: str, path: str, what: str, text: str = "", day: str = "", pic: int = 0) -> str:
        """text：跟圖放在同一條消息裡的一句話（10-26 她把圖發進群後想配一句，只能另外再發一條，撞上那個群的說話上限）。pic：圖冊編號"""
        name = self._gname(gid)
        try:
            how_sent = await self._deliver(gid, path, text)
        except Exception as e:
            if pic:
                self.gallery.update(pic, status="没发成", failed=self._send_why(e))
            return f"发到「{name}」没发成：{self._send_why(e)}"
        if pic:
            self.gallery.mark_sent(pic, f"「{name}」", late=how_sent == "late", umo=self.s.group_umo(gid))
        self._log("sent", group=gid, path=path, what=what, **({"text": text} if text else {}), **({"pic": pic} if pic else {}),
                  **({"day": day} if day else {}), **({"late": True} if how_sent == "late" else {}))
        said = f"，配的话是「{text}」" if text else ""
        note_outbox(self.s.group_umo(gid), self.s.fill(f"〈我〉把{what}（一张图）发到群里了{said}"), "群漫画")
        await self._note(f"[〈我〉把{what}发到「{name}」群里了{said}]")
        return f"把{what}{'连同那句话' if text else ''}发到「{name}」啦～"

    # ---------- 發圖（11-02：一定寫圖冊編號） ----------
    def _recent_lines(self, limit: int = 8, **kw) -> str:
        rows = self.gallery.recent(limit=limit, **kw)
        return "\n".join(self.gallery.line(r) for r in rows) or "（图册里还没有图）"

    def _gallery_path(self, it: dict) -> tuple[str, str]:
        """這一張現在能發的檔案路徑；回 (路徑, 拿不到的原因)。拼不起來的整頁在這裡重拼一次"""
        if it.get("need_combine"):
            paths = [(self.gallery.get(i) or {}).get("path", "") for i in it.get("parent") or []]
            if not paths or not all(p and Path(p).exists() for p in paths):
                return "", f"这组里有张图的文件不在了，拼不起来"
            whole = self._combine(str(it.get("group") or ""), paths)
            if not whole:
                return "", f"几张拼不成一张大图（{self.__dict__.get('_combine_why') or '原因不明'}），群漫画只发拼好的整页"
            self.gallery.update(it["id"], path=whole, file=self.gallery._rel(whole), need_combine=False)
            it = self.gallery.get(it["id"]) or it
        path = it.get("path", "")
        if not path or not (path.startswith("http") or Path(path).exists()):
            return "", f"图文件不在了（{it.get('file') or path}）"
        return path, ""

    def _post_facts(self, it: dict) -> str:
        """發出去之後回給她的事實：種類、什麼時候在哪畫的、用途、之前發過哪裡、拍的是什麼"""
        ts = datetime.fromtimestamp(it["ts"], TZ)
        kind = it["kind"] + (f"·{it['shot']}" if it["kind"] == "拍照" and it.get("shot") else "")
        if it["kind"] == "群漫画整页":
            what = f"{it.get('day', '')[5:]} 那天的 {it.get('n') or 1} 张{'拼成' if (it.get('n') or 1) > 1 else ''}，{ts:%H:%M} 画好"
        else:
            what = f"{ts:%m-%d %H:%M} {'在' + it['chat'] + '拍的' if it.get('chat') and it['kind'] == '拍照' else it.get('chat', '')}"
        before = [x for x in it.get("sent") or [] if not x.get("show")]
        was = "，之前发过：" + "、".join(sorted({x["to"] for x in before})) if before else "，之前没发过"
        if it.get("purpose"):
            what += f"，用途「{it['purpose']}」"
        tail = f"；拍的是：{it['prompt'][:60]}" if it.get("prompt") and it["kind"] in ("拍照", "说说配图") else ""
        return f"{kind}，{what}{was}{tail}"

    async def post(self, image: str = "", target: str = "", text: str = "") -> str:
        """把图册里指定编号的图发到群里（lively_comic_post）。一定要写编号；挡住时回的话只讲事实和这一道是谁定的"""
        text = re.sub(r"&&[^&]*&&", "", str(text or "")).strip()[:200]
        await self._refresh_names()
        self._one_pending()
        raw = str(image or "").strip()
        n = self.gallery.parse_id(raw)
        if n is None:
            head = "没发：没写发哪张（image 写图册编号）" if not raw else f"没发：「{raw[:20]}」不是图册编号（写 #123 或 123 都行）"
            return f"{head}。最近的图：\n{self._recent_lines()}"
        it = self.gallery.get(n)
        if not it:
            return f"没发：图册里没有 #{n}。最近的图：\n{self._recent_lines()}"
        kind = it["kind"]
        everyone = str(target or "").strip() in ("全部", "所有", "都发", "all")
        gid_t = ""
        if str(target or "").strip() and not everyone:  # 群號或群名裡的字（10-27 她寫「桐群」）
            gid_t, why = self._find_group(str(target).strip())
            if not gid_t:
                return self.s.fill(why)
        if kind == "形象":
            return f"没发：#{n} 是定做形象的图，不往群里发"
        if kind in SINGLE_KINDS:
            page = self.gallery.page_of(n)
            return (f"没发：#{n} 是群漫画里的{'一张' if kind == '群漫画单张' else '一张修过的图'}；群漫画照规矩拼成整页发"
                    + (f"，这一组的整页是 #{page['id']}" if page else "，这一组还没有整页") + "（〈主人〉定的）")
        if kind in ("拍照", "说说配图"):
            if it.get("where") != self._owner_umo():
                return self.s.fill(f"没发：#{n} 是 {datetime.fromtimestamp(it['ts'], TZ):%m-%d %H:%M} 的图（{it.get('chat') or '不知道在哪画的'}），"
                                   "不是〈主人〉私聊里画的；这种图程序不往群里转（〈主人〉定的）")
            path, why = self._gallery_path(it)
            if not path:
                return f"没发：#{n} {why}"
            groups = self._served() if everyone else [gid_t] if gid_t else self._groups()
            if not everyone and not gid_t and len(groups) != 1:
                return ("#%d 要发到哪个群？写 group（群号、群名里的字，或「全部」）：\n" % n
                        + ("\n".join(self._glabel(g) for g in groups) if groups else "还没有开着的群"))
            facts, out = self._post_facts(it), []
            for g in groups:
                res = await self._send_to(g, path, f"图册 #{n}（{kind}）", text, pic=n)
                out.append(f"发了 #{n} 到「{self._gname(g)}」：{facts}" + (f"；配的话「{text}」" if text else "") if "没发成" not in res else f"#{n} {res}")
            return "\n".join(out)
        if kind == "群漫画整页":
            gid = str(it.get("group") or "")
            if (gid_t and gid_t != gid) or everyone:
                return (f"没发：#{n} 是「{self._gname(gid)}」那天的群漫画，只能发回它自己的群，不往别的群发（〈主人〉定的）")
            if gid not in self._served():
                return f"没发：#{n} 的群「{self._gname(gid)}」现在不在〈我〉服务的群里"
            if (self.state.setdefault("held", {}).get(gid) or {}).get("page") == n or it.get("status") == "等主人看":
                return self.s.fill(f"没发：「{self._gname(gid)}」的群漫画〈主人〉说先看，还没放行；放行要在和〈主人〉的私聊里用 lively_comic_hold（〈主人〉定的）")
            path, why = self._gallery_path(it)
            if not path:
                self.gallery.update(n, status="没发成", failed=why)
                return f"没发：#{n} {why}；图留着，下次发还会再拼"
            it = self.gallery.get(n) or it
            facts = self._post_facts(it)
            res = await self._send_to(gid, path, f"{it.get('day', '')[5:]} 的群漫画（图册 #{n}）", text, day=it.get("day", ""), pic=n)
            if "没发成" in res:
                return f"#{n} {res}"
            for sid in it.get("parent") or []:
                self.gallery.set_status(sid, "已发")
            if (self.state["pending"].get(gid) or {}).get("day", it.get("day")) == it.get("day"):
                self.state["pending"].pop(gid, None)
                self._save()
            return f"发了 #{n} 到「{self._gname(gid)}」：{facts}" + (f"；配的话「{text}」" if text else "")
        return f"没发：#{n} 是{kind}，不往群里发"

    def _find_group(self, target: str) -> tuple[str, str]:
        """群號或群名裡的字 → 服務的群的群號；找不到、對上好幾個就回（"", 說明）"""
        t, served = target.strip(), self._served()
        if t.isdigit():
            return (t, "") if t in served else ("", f"群 {t} 不在〈我〉服务的群里")
        hits = [g for g in served if t and t in self._gname(g)]
        if len(hits) == 1:
            return hits[0], ""
        if hits:
            return "", f"名字里带「{t}」的群有好几个：{'、'.join(self._glabel(g) for g in hits)}，写群号就行"
        return "", f"没有名字里带「{t}」的群；〈我〉服务的群：{'、'.join(self._glabel(g) for g in served)}，写群号或者群名里的字都行"

    @filter.llm_tool("lively_comic_post")
    async def post_tool(self, event: AstrMessageEvent, image: str = "", group: str = "", text: str = ""):
        """把图册里指定编号的一张图发到群里，可以带一句话，和图放在同一条消息里发。每张画好的图都有编号：画好时的回传里、素材里的「图册.txt」里、或者用 lively_pic 看。发哪张一定要写 image，没写会列出最近的图。
        能发的：〈主人〉私聊里拍的照片；某个群的群漫画整页（只能发回它自己的群，群漫画照规矩拼成整页发，单张、修过的单张不单发）。别人私聊里拍的图、说说配图、定做形象不往群里发。返回实际发了什么（种类、哪天画的、用途、之前发过哪里）；没发成会说是哪一道挡的。
        谁请你转、或者你自己想发，都可以用；转不转由你。

        Args:
            image(string): 发哪张：图册编号，写 123 或 #123 都行
            group(string): 发到哪个群：群号、群名里的字；群漫画整页不用写（只能发回它的群）；照片没写、又开了好几个群时会返回要问的
            text(string): 跟图一起发的一句话，不带就只发图
        """
        return await self.post(image=image, target=group, text=text)

    @filter.llm_tool("lively_pic")
    async def pic_tool(self, event: AstrMessageEvent, action: str = "看", image: str = "", group: str = "", day: str = "", kind: str = ""):
        """看图册，或者把图册里的一张拿给当前聊天里的人看。图册里每张画好的图（拍照、群漫画整页、修图……）都有编号、种类、哪天在哪画的、用途、发过哪里。
        看：列最近的几张，可以按群（group）、哪天（day，写 11-01 或 2026-11-01）、种类（kind，例如 群漫画整页、拍照）找。
        给这里：把 image 那张发到当前聊天（不算发群，不影响那组群漫画发没发、有没有存着）；〈主人〉的私聊里图册里什么都能拿，别的聊天（包括〈主人〉在群里叫你的时候）只能拿在这个聊天画的、或者已经发到这个群里的。

        Args:
            action(string): 看、给这里
            image(string): 给这里时写图册编号
            group(string): 看时按群找：群号或群名里的字
            day(string): 看时按哪天找
            kind(string): 看时按种类找
        """
        here = event.unified_msg_origin
        owner = here == self._owner_umo()  # 「主人那边全拿」指〈主人〉的私聊；主人在群里叫她时跟别人一样，只能拿这个群能拿的
        await self._refresh_names()
        if "给" in str(action or "") or "发" in str(action or ""):
            n = self.gallery.parse_id(image)
            it = self.gallery.get(n) if n else None
            if not it:
                return f"没有这张：{str(image or '')[:20] or '没写编号'}。最近的图：\n{self._recent_lines(limit=8) if owner else self._recent_allowed(here)}"
            if not owner and not self._pic_allowed(it, here):
                return self.s.fill(f"没给：#{n} 不是在这个聊天里画的，也没发到这个群里；别的聊天里的图只有〈主人〉的私聊才能拿（〈主人〉定的）")
            path, why = self._gallery_path(it)
            if not path:
                return f"没给：#{n} {why}"
            try:
                await self._send_checked(here, path, "")
            except Exception as e:
                return f"没给成：#{n} 发到这里没发成（{self._send_why(e)}）"
            where = "〈主人〉私聊" if here == self._owner_umo() else "这个群" if ":GroupMessage:" in here else "这个私聊"
            self.gallery.mark_sent(it["id"], where, show=True, umo=here)
            extra = ""
            if it["kind"] == "群漫画整页" and it.get("status") not in ("已发",):
                extra = f"；这组群漫画{it.get('status') or '还没发'}，拿给这里看不算发群"
            return self.s.fill(f"给这里发了 #{it['id']}：{self._post_facts(it)}{extra}")
        gid = ""
        if str(group or "").strip():
            gid, why = self._find_group(str(group).strip())
            if not gid:
                return self.s.fill(why)
        d = str(day or "").strip()
        if d and len(d) <= 5:
            d = f"{datetime.now(TZ).year}-{d}"
        rows = self.gallery.recent(limit=10 if owner else 80, kind=[kind] if str(kind or "").strip() else None, group=gid or None, day=d or None)
        if not owner:
            rows = [r for r in rows if self._pic_allowed(r, here)][:10]
        if not rows:
            return "图册里没有符合的图" + ("" if owner else "（别的聊天里的图只有〈主人〉的私聊才看得到）")
        return "\n".join(self.gallery.line(r) for r in rows)

    def _recent_allowed(self, here: str) -> str:
        rows = [r for r in self.gallery.recent(limit=80) if self._pic_allowed(r, here)][:8]
        return "\n".join(self.gallery.line(r) for r in rows) or "（这个聊天能拿的图里还没有）"

    def _pic_allowed(self, it: dict, here: str) -> bool:
        if it.get("where") == here or here in (it.get("also") or []):
            return True
        gid = here.rsplit(":", 1)[-1] if ":GroupMessage:" in here else ""
        return bool(gid and it.get("kind") == "群漫画整页" and str(it.get("group")) == gid
                    and any(not x.get("show") for x in it.get("sent") or []))

    # ---------- 主人請她補畫 ----------
    def _redo_max(self) -> int:
        try:
            return max(0, int(self.s.get("comic_redo_max", 2)))
        except (TypeError, ValueError):
            return 2

    def _redo_used(self) -> int:
        day = datetime.now(TZ).strftime("%Y-%m-%d")
        if self.state.get("redo_day") != day:
            self.state["redo_day"], self.state["redo_count"] = day, 0
        return int(self.state.get("redo_count") or 0)

    def _redo_refund(self, gid: str = ""):
        """沒畫出圖（取不到話題、畫圖那步失敗）的補畫不算進今天的張數；補那天沒畫成的，那天那個群還能再補一次"""
        key = (self._redo.get(gid) or {}).get("makeup") if gid else ""
        if key:
            self.state.setdefault("makeup", {}).pop(key, None)
            self._save()
        elif (self._redo.get(gid) or {}).get("counted", True) and self._redo_used() > 0:  # 〈主人〉直接要的沒算進去，也不退
            self.state["redo_count"] -= 1
            self._save()

    @filter.llm_tool("lively_comic_redo")
    async def redo_tool(self, event: AstrMessageEvent, group: str, day: str = "今天", again: bool = False):
        """照每天群漫画的做法给一个群重新画：群分析插件取那天的话题，你写分镜、定名字牌，挑几件事、一件事画一张四格，画好一张一张给你看，哪格不对可以修图或重画，看完连同你配的话发到那个群。
        谁请你补画、重画群漫画，或者你自己想画，你也愿意的时候可以用。
        一张要好几分钟（取话题、写分镜、画、看，改一次再加几分钟），所以工具先回「开始画了」；发出去或者没画成，会在叫你画的这个聊天里告诉你（你自己在任务里开的，照旧记下来，下一轮看得到）。每张都要花画图的钱。
        不同群的补画可以同时开、各画各的；只有同一个群正在画着才要等它画完。
        补那天定时那张没画成的：每个群每天一次，不算补画张数；那天已经发到群里的，再画是第二张，要写 again，算补画张数（一天有限）；那天画好了没发成的图还留着，用 lively_comic_post 写图册编号发，不用重画。
        〈主人〉在对话里直接要的，不算一天那几张的上限（主人点头就画）。

        Args:
            group(string): 哪个群：群号或群名里的字
            day(string): 画哪天的：今天、昨天、前天；不写就是今天
            again(boolean): 那天的已经发到群里了还要再画一张时写 true
        """
        await self._refresh_names()
        gid, why = self._find_group(str(group or ""))
        if not gid:
            return self.s.fill(f"没画：{why}")
        d = str(day or "")
        offset = next((n for k, n in REDO_DAYS.items() if k in d), 0)
        label, name = self._window(offset)[2], self._gname(gid)
        if not self.state["enabled"]:
            return "没画：群漫画的总开关关着"
        if gid in self.state.get("off_groups", []):
            return f"没画：「{name}」的群漫画单独关着（面板「群里」页能开）"
        if self._lock(gid).locked():
            return f"没画：「{name}」的群漫画正在画着，画完会照常给你看、发出去。{self._redo_board(offset)}"
        theday = self._day_of(offset)
        pend = self.state["pending"].get(gid) or {}
        if pend and pend.get("day", "") == theday and time.time() - pend.get("ts", 0) <= PENDING_TTL:
            return (f"没画：「{name}」{label}的群漫画 {self._at_ts(pend['ts'])} 画好了，发到群里没发成（{pend.get('failed') or '发送出错'}），"
                    f"图还留着（整页是图册 #{(self.gallery.find_path(pend.get('path', ''), '群漫画整页') or {}).get('id', '?')}）；"
                    "用 lively_comic_post 写 image 编号就能发，不用重画、不花钱")
        held = self.state.setdefault("held", {}).get(gid) or {}
        if held and held.get("day") == theday:
            if not again:
                return (f"没画：「{name}」{label}的群漫画 {self._at_ts(held['ts'])} 画好了存着，〈主人〉说先看，还没放行（图册 #{held['page']}）；"
                        "放行或不发了用 lively_comic_hold；想整组重画写 again（重画的这组也先存着，存着的这组作废）")
            self.state.setdefault("hold", {})[gid] = {"since": int(time.time())}  # 重画的也先存着
        rec = self._day_record(gid, theday)
        mx, used = self._redo_max(), self._redo_used()
        own = self.s.is_owner(str(event.get_sender_id() or ""))
        if rec["sent"] and not again:
            more = f"，后来又补画发过 {rec['redo_sent']} 张" if rec["redo_sent"] else ""
            late = "（发的时候 QQ 报了超时，其实发到了）" if rec["late"] else ""
            return (f"没画：「{name}」{label}的群漫画 {self._at_ts(rec['sent'])} 已经发到群里了{late}{more}。"
                    f"再画一张就是那天的第二张，要画就写 again，算补画张数（今天还能补 {max(0, mx - used)} 张）\n"
                    + self._redo_board(offset))
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        ran = offset > 0 or (self.state["last_day"].get(gid) == today and gid not in self.state["inflight"])
        key = f"{theday}:{gid}"
        made = self.state.setdefault("makeup", {})
        makeup = ran and not rec["sent"] and key not in made
        if makeup:  # 補那天定時那張沒畫成的：每群每天一次，不算張數
            made[key] = int(time.time())
            for k in [k for k in made if k[:10] < self._day_of(7)]:
                made.pop(k, None)
        elif own and mx > 0:  # 10-31 用戶定：補畫上限只管她自己要畫的，〈主人〉在對話裡直接要的不卡、也不算進去（mx=0 是關掉補畫，照樣擋）
            logger.info(f"[lively_comic] 〈主人〉在对话里要的补画，不算今天的补画张数（{used}/{mx}）")
        elif used >= mx:
            return self.s.fill(f"没画：是补画张数的额度到了——今天已经补画了 {used} 张，一天最多补画 {mx} 张"
                               "（那天定时那张没画成的不算；〈主人〉在对话里直接叫你画的也不算）" + ASK_OWNER)
        else:
            self.state["redo_count"] = used + 1
        self._save()
        mins = max(5, int(self.s.get("comic_redo_min", 20) or 20))
        asker = str(event.get_sender_id() or "")
        redo = {"due": int(time.time() + mins * 60), "origin": event.unified_msg_origin, "ts": int(time.time()),
                "asker": "" if self.s.is_owner(asker) else (event.get_sender_name() or asker), "asker_qq": asker,
                **({"makeup": key} if makeup else {}), **({"counted": False} if own and mx > 0 else {})}
        self._log("redo", group=gid, offset=offset, day=theday, umo=redo["origin"], makeup=makeup, again=bool(again))
        logger.info(f"[lively_comic] {redo['asker'] or '主人'}请她补画「{name}」{label}的群漫画")
        task = asyncio.create_task(self._redo_run(gid, offset, redo))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        per = -(-int(self._draw_secs.get(gid, DRAW_SECS_GUESS)) // 60) + 1
        tail = ""
        now = datetime.now(TZ)
        if offset == 0 and self.state["last_day"].get(gid) != now.strftime("%Y-%m-%d") and now.strftime("%H:%M") < self._start_at():
            tail = f"；今天定时那张 {self._start_at()} 还会照常画、{self.comic_at} 发"
        tail += "；别的群要补画现在就能开，不用等这张画完"
        return (f"开始画了：「{name}」{label}的群漫画。先取话题、写分镜、画，第一张大概 {per} 分钟；画好先给你看，"
                f"哪格不对可以改到 {self._at_ts(redo['due'])}，"
                + (f"画好先存着，等〈主人〉放行（〈主人〉说了先看）。" if self._hold_active(gid) else f"看完就连同你配的话发到「{name}」。")
                + (f"这张是补{label}定时那张没画成的，不算补画张数（{rec['failed'] or '那天没发'}）；今天还能补画 {max(0, mx - used)} 张"
                   if makeup else (f"这是〈主人〉在对话里直接要的，不算补画张数；今天还能补画 {max(0, mx - used)} 张" if own and mx > 0
                                   else f"今天还能补画 {max(0, mx - used - 1)} 张")) + tail
                + "\n" + self._redo_board(offset, gid))

    @staticmethod
    def _at_ts(ts: float) -> str:
        return datetime.fromtimestamp(ts, TZ).strftime("%H:%M")

    async def _redo_run(self, gid: str, offset: int, redo: dict, done_path: str = ""):
        """補畫一張（背景跑）：發出去了 _publish 會記；沒畫成把事實交給她（跟不跟主人說她定），在別的聊天叫的那邊也記一筆"""
        label, name = self._window(offset)[2], self._gname(gid)
        try:
            msg = await self.draw(gid, offset, done_path=done_path, redo=redo)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[lively_comic] 补画「{name}」的群漫画出错: {e}", exc_info=True)
            msg = f"{label}「{name}」的群漫画没画成：{str(e)[:120]}"
        logger.info(f"[lively_comic] 补画群 {gid}: {msg}")
        done = msg in DONE_MSGS
        held_id = (self.state.setdefault("held", {}).get(gid) or {}).get("page")
        facts = (f"{redo.get('asker') or '〈主人〉'}请〈我〉补画的群漫画："
                 + ((f"{label}「{name}」的画好了，〈主人〉说先看，存着没发（图册 #{held_id}），放行用 lively_comic_hold" if msg == HELD_MSG
                     else f"{label}「{name}」的画好了，已经发到「{name}」") if done else msg))
        origin = redo.get("origin") or ""
        if await self._wake_origin(origin, str(redo.get("asker_qq") or ""), facts):
            if done or origin == self._owner_umo():
                return
        elif done:
            return
        await self._report(facts)
        if origin and origin != self._owner_umo():
            note_outbox(origin, self.s.fill(facts), "群漫画")

    async def _wake_origin(self, umo: str, asker: str, facts: str) -> bool:
        """補畫有結果了，在當初叫她畫的那個聊天給她一輪（10-31 用戶定：她說了「等这张出来就接着开」，畫完卻沒人叫她，
        桐群 23:27 發了，晓白要等主人 23:38 問才開）。走自主插件的 wake_for；沒載入、叫的是她自己（任務裡開的）就回 False"""
        try:
            meta = self.context.get_registered_star("astrbot_plugin_lively_mind")
            mind = meta.star_cls if meta and meta.activated else None
        except Exception:
            mind = None
        if not umo or mind is None or not hasattr(mind, "wake_for"):
            return False
        qq = asker if ":GroupMessage:" in umo else umo.rsplit(":", 1)[-1]
        where = "这个群里" if ":GroupMessage:" in umo else "和 TA 的私聊里"
        note = (f"〈我〉之前在这里接的补画有结果了——{facts}。这一轮〈我〉要是说话，会发在{where}；"
                "说不说、说什么、接下来要不要做别的照平常聊天来，不用说就用 lively_skip_reply")
        return await mind.wake_for(umo, qq, self.s.fill(note), {"comic_redo": True})

    def _how_post(self) -> str:
        if not self.s.get("comic_look", True):
            return "画完直接发群"
        fix = f"，哪格不对她可以改（每张最多 {self._fix_max()} 次，赶得上就换）" if self._fix_max() else ""
        redo = f"；你请她补画、重画的话她用自己的工具画（一天最多 {self._redo_max()} 张）" if self._redo_max() else ""
        return f"{self._start_at()} 开始取话题、画，画完先给她看{fix}，到 {self.comic_at} 照发，配什么话她定{redo}"

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=1440)
    async def owner(self, event: AstrMessageEvent):
        if not self.s.is_owner(event.get_sender_id()):
            return
        text = (event.message_str or "").strip().translate(T2S)
        if not text.startswith("群漫画"):
            return
        arg = text[3:].strip()
        reply = None
        mg = re.match(r"^(开|开启|关|关闭)\s*(\d{5,12})$", arg)
        if mg:
            reply = self.set_group(mg.group(2), mg.group(1) in ("开", "开启"))
        elif arg in ("开", "开启"):
            self.state["enabled"] = True
            reply = f"每天 {self.comic_at} 画群漫画，{self._how_post()}"
        elif arg in ("关", "关闭"):
            self.state["enabled"] = False
            reply = "不自动画群漫画了"
        elif arg in ("", "状态"):
            await self._refresh_names()
            reply = (f"群漫画：{'开' if self.state['enabled'] else '关'}，每天 {self.comic_at} 画，{self._how_post()}；"
                     f"各群：{'、'.join(self._glabel(g) + ('' if g in self._groups() else '·关') for g in self._served()) or '没有服务的群'}\n"
                     "「群漫画 关 群号」单独关一个群")
        if reply is None:
            return  # 「群漫画画得真好」之類的普通聊天，交給她回
        self._save()
        event.stop_event()
        await event.send(MessageChain().message(self.s.admin_text(reply)))

    async def _draw_and_report(self, gid: str, offset: int = 0, auto: bool = False, done_path: str = ""):
        try:
            msg = await self.draw(gid, offset, auto, done_path=done_path)
            if msg not in DONE_MSGS:
                await self._report(msg)
        except Exception as e:
            logger.error(f"[lively_comic] 画漫画失败: {e}", exc_info=True)
            await self._report(f"重启前没画完的「{self._gname(gid)}」群漫画，接着画也没画成：{str(e)[:120]}")
