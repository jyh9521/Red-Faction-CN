# 原版游戏目录清单（安装 Dash Faction 之前）

快照：`snapshots/00-vanilla.json` · 2026-07-29 · **73 个文件 / 2.1 GB**
版本：Steam 数字版 **v1.21**（`build.ver` = 177）

> 快照记录了每个文件的大小、修改时间和 SHA-256（大于 64MB 的文件取首尾各 4MB + 大小的部分哈希）。
> 装完 Dash Faction 后跑 `snapshot.py diff` 就能精确列出它动了什么。

---

## 可执行文件

| 文件 | 大小 | 说明 |
|---|---|---|
| `RF.exe` | 2.8 MB | **游戏主程序**。Dash Faction 只认英文 v1.20，这个 v1.21 的会被替换 |
| `RED.exe` | 2.0 MB | 官方关卡编辑器（Red Faction EDitor） |
| `RedFaction.exe` | 6.4 MB | 官方启动器。DF 的 setup 可选把它替换成指向 DF 启动器的符号链接 |
| `UpdateLauncher.exe` | 991 KB | 启动器的自更新程序 |
| `Patchw32.dll` | 182 KB | RTPatch 增量补丁引擎，配合启动器更新用 |
| `binkw32.dll` | 291 KB | Bink 视频解码器，播放过场动画 |
| `eax.dll` | 41 KB | Creative EAX 2.0 音效 |

## VPP 数据包（游戏本体资源，共约 1.0 GB）

| 文件 | 大小 | 内容 |
|---|---|---|
| `tables.vpp` | 1.3 MB | **29 个配置/文本表**，含 `strings.tbl`、`endgame.tbl` —— 汉化主战场 |
| `levels1/2/3.vpp` | 201 MB | 战役关卡，各含 `.rfl` 关卡 + `*_text.tbl` **字幕表** —— 汉化主战场 |
| `levelsm.vpp` | 50 MB | 26 个多人地图 |
| `maps1~4.vpp` | 318 MB | 通用贴图，3447 张 tga + 94 个 vbm |
| `maps_en.vpp` | 12 MB | **英文场景标牌贴图 229 张** —— 按语言区分的贴图包，将来扩范围用 |
| `ui.vpp` | 24 MB | 界面素材：162 tga + 17 vbm + **5 个 `.vf` 位图字体** —— 字体瓶颈所在 |
| `meshes.vpp` | 16 MB | 模型：427 v3m + 95 v3c + 61 vfx |
| `motions.vpp` | 16 MB | 1009 个 `.rfa` 骨骼动画 |
| `audio.vpp` | 246 MB | 2568 个语音/音效 wav |
| `music.vpp` | 209 MB | 107 个音乐 wav |

`bluebeard.bty`（369 KB）是音效辅助信息表——记录每个音效是否循环、循环点在哪、属于什么类型，文件开头有自述注释。

## 过场动画（172 MB，**存在完整重复**）

`data\movies\` 和 `RF_2\data\movies\` 两份内容完全一样：

- `intro.bik` 61 MB · `end.bik` 46 MB · `sumtrailer.bik` 37 MB · `thqlogo.bik` 7 MB
- `technochunk.exe` 20 MB —— 一个 UPX 压缩的 Win32 程序，混在影片目录里，非游戏运行所需

发布整合包时这两份重复的 172 MB 都不用带。

## 零售版安装镜像（RF_1 / RF_2，约 750 MB）

Steam 版把当年的光盘安装文件一并塞了进来，**游戏运行完全不需要**：

- `RF_1\` —— InstallShield 安装程序（`data2.cab` 单个就 512 MB）+ `directx8\` 运行库
- `RF_2\` —— `data3.cab` + 又一份 `music.vpp`（209 MB，与根目录那份重复）

也就是说 2.1 GB 里有将近 **1 GB 是重复或无用的**。

## 配置与运行时文件（每次启动都可能变，比对时自动忽略）

| 文件 | 说明 |
|---|---|
| `players.cfg` | 玩家配置、按键绑定 |
| `rfd3d.id` | 显卡检测结果缓存（当前记录：NVIDIA GeForce RTX 4070 Laptop） |
| `svrlist.adr` / `favlist.adr` / `banlist.txt` | 服务器列表 / 收藏 / 封禁 |
| `console_history` | 控制台历史 |
| `dedicated_server.txt` | 专用服务器配置模板 |
| `Red\red.cfg` | 关卡编辑器配置 |
| `savegame\` | 存档目录（当前只有 `steam_autocloud.vdf`） |

## 其他

- `red.hlp` + `RED.CNT` —— 编辑器的 WinHelp 帮助文件
- `README.TXT` —— 官方说明，里面就写着 Alt+Tab 有问题、要用 Shift+Esc 退出
- `mods\MOD Tutorial.txt` —— **官方 mod 制作说明**，汉化包走的 `-mod` 机制依据就在这里
- `user_maps\` —— 用户自制地图目录（空）

---

## 整合版发布的初步想法

真正需要打包的只有三类：

1. Dash Faction 本体（等装完 diff 出来才知道具体是哪些文件）
2. 汉化 mod：`dist/mods/rfcn/rfcn.vpp`（目前 382 KB）
3. 改造过的字体资源（待定，取决于字体方案）

原版那 1 GB 冗余（`RF_1`、`RF_2`、重复的 movies）一概不碰、不带。
`tables.vpp` 和各 `levels*.vpp` **保持原样只读** —— 德文版就是因为直接改 `tables.vpp`
导致多人游戏不可用，这是 PCGW 明确记载的前车之鉴。

## 下一步

装完 Dash Faction 后执行：

```bash
python tools/snapshot.py take .. snapshots/01-dashfaction.json --label "装 Dash Faction 后"
python tools/snapshot.py diff snapshots/00-vanilla.json snapshots/01-dashfaction.json --md DASHFACTION-DIFF.md
```
