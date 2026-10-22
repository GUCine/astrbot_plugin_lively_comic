# 每日群聊漫畫

> 每天把群聊畫成群漫畫（基於群分析插件），主人審核後發群；主人可以讓機器人畫畫

AstrBot 插件，屬於「擬真群友」（lively）插件套件。適用 AstrBot >=4.29.0 + NapCat（aiocqhttp）。

主人、群、機器人名字、人設用詞這些共用設定在 [astrbot_plugin_lively_gate](https://github.com/GUCine/astrbot_plugin_lively_gate) 裡填，建議一起裝。

## 功能

```text
每日群漫畫：先私信主人預覽，主人說「發群」才發到群裡。

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
```

## 依賴

[群分析總結插件 astrbot_plugin_qq_group_daily_analysis](https://github.com/SXP-Simon/astrbot_plugin_qq_group_daily_analysis)：群漫畫的話題提取和畫圖配置都用它的（在那個插件裡配好畫圖模型，並關掉它自己的定時分析和自動漫畫）。

## 配置

在 AstrBot WebUI 的插件配置裡填，或者直接編輯 `data/config/astrbot_plugin_lively_comic_config.json`。留空的公共項（主人、群、機器人名字、平台）會用 astrbot_plugin_lively_gate 裡填的。

| 配置項 | 說明 | 預設 |
| --- | --- | --- |
| `groups` | 能畫群漫畫的群：留空 = 門禁插件裡服務的所有群，預設都開；每個群可以在面板裡或私信「群漫畫 關 群號」單獨關 | （空） |
| `comic_at` | 每天幾點畫群漫畫：24 小時制 HH:MM（北京時間） | "22:00" |
| `draw_daily_max` | 主人每天最多讓畫幾張圖 | 20 |
| `keep_image_days` | 畫好的圖保留幾天：過期自動刪除（還在等審核的不刪） | 14 |
| `self_look` | 機器人出鏡時的外觀描述（英文提示詞）：主人讓畫「你自己」時加在提示詞前面，例如 The main character is a cute chibi cat girl with ...。留空 = 不額外描述長相 | （空） |
| `self_ref_image` | 機器人出鏡時的參考圖：圖片路徑，絕對路徑或相對 AstrBot 的 data 目錄，例如 plugin_data/astrbot_plugin_qq_group_daily_analysis/reference_images/me.jpg。留空不帶參考圖 | （空） |
| `owner_qq` | 主人 QQ（留空用門禁插件裡填的） | （空） |

## 資料

執行資料在 `data/plugin_data/astrbot_plugin_lively_comic/`。

## 許可

MIT，見 [LICENSE](LICENSE)。
