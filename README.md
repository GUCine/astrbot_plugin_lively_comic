# 每日群聊漫畫

> 每天把群聊畫成群漫畫（基於群分析插件），主人審核後發群；主人可以讓機器人畫畫

AstrBot 插件，屬於「擬真群友」（lively）插件套件。適用 AstrBot >=4.29.0 + NapCat（aiocqhttp）。

主人、群、機器人名字、人設用詞這些共用設定在 [astrbot_plugin_lively_gate](https://github.com/GUCine/astrbot_plugin_lively_gate) 裡填，建議一起裝。

## 功能

```text
每日群漫畫：每天到點把各群當天的聊天挑幾件事畫成一張格子漫畫，畫好直接發到群裡，再跟主人說一聲。

畫漫畫用的是「群分析總結」插件（SXP-Simon/astrbot_plugin_qq_group_daily_analysis）的內部服務和畫圖配置，
分鏡由〈我〉自己定（11-02 起沒有退路：分鏡寫壞了先請她重寫一次，還是壞就那晚那個群沒有群漫畫，不再退回那個插件畫長圖）。那個插件自己的定時分析、自動漫畫都關著，它會直接往群裡髮長圖的 LLM 工具也擋著。

畫圖工具 lively_draw：主人和〈我〉好感度 draw_min_score 以上的人才有，畫好發到當前聊天或 TA 的私聊（每天最多 draw_daily_max 張）。
lively_comic_post：〈我〉把剛在主人私聊裡畫的圖轉發到群裡（只有主人那邊有）。

主人私信指令：群漫畫 開 / 關 / 狀態；群漫畫 開 群號 / 群漫畫 關 群號（單獨開關某個群，服務的群預設都開）
（10-26 拿掉了手動補畫、先審後發、「發群」攔截這幾條：群漫畫只有每天定時那張）
```

## 依賴

[群分析總結插件 astrbot_plugin_qq_group_daily_analysis](https://github.com/SXP-Simon/astrbot_plugin_qq_group_daily_analysis)：群漫畫的話題提取和畫圖配置都用它的（在那個插件裡配好畫圖模型，並關掉它自己的定時分析和自動漫畫）。

## 配置

在 AstrBot WebUI 的插件配置裡填，或者直接編輯 `data/config/astrbot_plugin_lively_comic_config.json`。留空的公共項（主人、群、機器人名字、平台）會用 astrbot_plugin_lively_gate 裡填的。

| 配置項 | 說明 | 預設 |
| --- | --- | --- |
| `groups` | 能畫群漫畫的群：留空 = 門禁插件裡服務的所有群，預設都開；每個群可以在面板裡或私信「群漫畫 關 群號」單獨關 | （空） |
| `comic_at` | 每天幾點畫群漫畫：24 小時制 HH:MM（北京時間） | "22:00" |
| `draw_daily_max` | 每天最多讓畫幾張圖：所有人加起來，說說配圖也算在裡面 | 20 |
| `draw_min_score` | 好感度到多少能叫〈我〉畫圖：主人不看這個；畫圖用的是 GPT 的模型，露骨的畫面會被審核擋掉 | 70 |
| `keep_image_days` | 畫好的圖保留幾天：過期自動刪除（還在等審核的不刪） | 14 |
| `self_look` | 機器人出鏡時的外觀描述（英文提示詞）：主人讓畫「你自己」時加在提示詞前面，例如 The main character is a cute chibi cat girl with ...。留空 = 不額外描述長相 | （空） |
| `self_ref_image` | 機器人出鏡時的參考圖：圖片路徑，絕對路徑或相對 AstrBot 的 data 目錄，例如 plugin_data/astrbot_plugin_qq_group_daily_analysis/reference_images/me.jpg。留空不帶參考圖 | （空） |
| `owner_qq` | 主人 QQ（留空用門禁插件裡填的） | （空） |
| `storyboard_provider_id` | 写群漫画分镜的模型：用〈我〉的人格挑今天值得画的事、写台词和每个人的样子。留空用 AstrBot 当前默认的模型 | （空） |
| `comic_size` | 群漫画的尺寸：竖着的格子漫画，默认 1024x1536（2:3）。画图服务不支持就改回 1024x1024 | "1024x1536" |
| `comic_panels_min` | 群漫画最少几格 | 2 |
| `comic_panels_max` | 群漫画最多几格：画几格〈我〉自己定，在这个范围里 | 6 |
| `comic_owner_look` | 群漫画里主人的样子：英文，例如 messy black hair, navy hoodie, glasses；留空就每次由分镜定（都画成年轻群友，不画成长辈）。头上标主人的群名片 | （空） |
| `comic_cast_max` | 群漫画最多标几个人：话题里的人在前，再按今天说话多少补；名字用〈我〉给 TA 起的称呼，和主人撞名的换回群名片 | 10 |

## 資料

執行資料在 `data/plugin_data/astrbot_plugin_lively_comic/`。

## 許可

MIT，見 [LICENSE](LICENSE)。
