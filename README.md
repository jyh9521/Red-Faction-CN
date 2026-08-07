# 《红色派系》简体中文汉化 —— 源码与译文

Red Faction (2001) Simplified Chinese localization — source and translations.

发布版补丁请到 [Releases](../../releases) 下载。这个仓库放的是**做出那个补丁所需的一切**。

---

## 这里有什么

| 目录 | 内容 |
|---|---|
| `translation/` | 全部译文。界面、剧情字幕、NPC 语音、过场字幕、标牌名词表、视频字幕 |
| `patches/` | `apply_patch.py` —— 对 Alpine Faction 源码的 142 处改动，每一处都附了原因 |
| `tools/` | 构建工具：打包 vpp、字体子集化、TGA 读写、标牌导出、语音识别 |
| `upstream-pr-veh/` | 提交给上游 Alpine Faction 的异常记录器（已合并的那个 PR） |
| `docs/` | 技术笔记、踩坑记录、上游 bug 报告 |

**没有游戏资源。** 标牌贴图、过场视频、字体文件都不在这里，原因见下。

---

## 怎么重建

看 [`BUILDING.md`](BUILDING.md)。简短版：

1. 拿一份 Alpine Faction 源码（tag `v1.3.0_Bakeapple`）
2. 跑 `python patches/apply_patch.py <源码目录>` 打补丁
3. 编译出 `AlpineFaction.dll`
4. 跑 `python tools/build_all.py` 打包 `rfcn.vpp`

`build_all.py` 需要 Noto Sans CJK 字体和一份游戏的 `tables.vpp`，**只能在 Linux 上跑**（原因见 BUILDING.md）。

---

## 为什么有些东西不在这里

| 内容 | 为什么 |
|---|---|
| 176 张中文标牌贴图 | 底图派生自游戏材质，整张图是派生作品。可以从发布的标牌包里取出来 |
| 烧了字幕的过场视频 | 同上 |
| Noto Sans CJK 字体 | 不是本项目的东西，从上游取，见 BUILDING.md |
| 语音识别模型 | 同上，而且体积不适合 git |
| 编译好的 DLL | 在 Releases 里 |

---

## 许可

**译文、转写、构建工具**采用 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.zh)。

想拿去做繁体版、或者以此为基础做其他语言的本地化，随意——保留署名并同样开放就行。

**`patches/apply_patch.py` 描述的是对 Alpine Faction（MPL-2.0）的修改。**
打好补丁的完整源码见 [`rf-cn` 分支](../../tree/rf-cn)，遵循 MPL-2.0。

《红色派系》版权归 Volition 及 THQ Nordic 所有，本项目与两者无隶属关系。
