# 第三方组件与许可声明

《红色派系》(Red Faction, 2001) 简体中文汉化包。

本包由多个来源的组件构成，各自适用不同的许可条款，分列如下。

---

## 1. Alpine Faction（引擎补丁）— MPL-2.0

本汉化包中的 `AlpineFaction.dll` 是 **Alpine Faction 的修改版本**。

- 上游项目：<https://github.com/GooberRF/alpinefaction>
- 上游许可：Mozilla Public License 2.0
- 基线版本：`v1.3.0_Bakeapple`

MPL-2.0 是文件级 copyleft。我们修改过的源文件同样以 MPL-2.0 提供：

**修改后的完整源码：** `<在此填入你的 GitHub 分支 URL>`

改动摘要（共 140 处）：

| 类别 | 内容 |
|---|---|
| 字体系统 | 字形索引由单字节改为 Unicode 码点，加入 UTF-8 解码 |
| 断行 | `gr_split_str` 替换为符合 CJK 规则的版本 |
| 语音字幕 | 新增独立字幕通道，按 wav 文件名查表显示 |
| 界面文本 | Alpine 自有 UI 的硬编码字符串替换为中文 |
| 诊断 | 新增异常记录器（已提交上游） |

原始的 MPL-2.0 许可全文见随包的 `LICENSE-MPL-2.0.txt`。

> 若你只想要未修改的 Alpine Faction，请从上游项目获取，不要用本包里的 DLL。

---

## 2. Noto Sans CJK SC（中文字体）— SIL Open Font License 1.1

`rfcn.vpp` 内的 `regularfont.ttf` 和 `boldfont.ttf` 是 Noto Sans CJK SC 的**子集**
——只保留译文实际用到的字形，以控制体积和显存占用。

- 字体：Noto Sans CJK SC，Version 2.004
- 版权：© 2014-2021 Adobe (<http://www.adobe.com/>)
- 许可：SIL Open Font License, Version 1.1
- 许可全文：<http://scripts.sil.org/OFL>，亦见随包的 `LICENSE-OFL-1.1.txt`
- Noto 是 Google Inc. 的商标

Noto Sans CJK 未声明保留字体名（Reserved Font Name），故子集版本保留原族名。
按 OFL 条款，这两个字体文件不得单独出售。

---

## 3. 高清标牌贴图 — 基于 AI Upscale Pack

`zz_rfcn_signage.vpp` 内的中文标牌，是在以下高清材质包的基础上重绘文字得到的：

- 原始放大：Captain_Dagon，ESRGAN 4x AI Upscale Pack
- 重新打包：Goober
- 来源：<https://www.factionfiles.com/ff.php?action=file&id=7630>
- 授权：已获原作者许可

> **署名要求待确认** —— 请把原作者要求的确切署名文字填进本节，
> 或注明「作者未提出特定要求」。

---

## 4. 原版游戏资源 — Volition / THQ Nordic

本包包含从原版游戏资源派生的内容：

- 标牌贴图（在原版材质上重绘文字）
- 过场动画 `intro.bik` / `end.bik`（在原版视频上叠加字幕后重新编码）

这些内容**仅供已合法拥有《红色派系》的玩家使用**，不构成对原版游戏资源的独立分发。
《红色派系》的版权归 Volition 及 THQ Nordic 所有。本项目与两者均无隶属关系。

---

## 5. 翻译文本与工具 — CC BY-SA 4.0

以下内容为本项目原创，不派生自上述任何组件，采用
**知识共享 署名-相同方式共享 4.0 国际（CC BY-SA 4.0）**：

- 全部中文译文（界面、剧情字幕、NPC 语音字幕、过场字幕）
- 573 条原版无文本语音的转写（经语音识别后人工校对）
- 8 场即时演算过场的转写与翻译（游戏本身无任何文本）
- 构建与打包工具（`rf_cn/tools/`、`rf_cn/patches/`）

许可全文：<https://creativecommons.org/licenses/by-sa/4.0/deed.zh>

欢迎在署名并同样开放的前提下派生使用 —— 比如做繁体中文版，
或以此为基础做其他语言的本地化。

---

## 免责声明

我不是律师，以上是按各许可条款的通常理解整理的，不构成法律意见。
若对合规性有疑虑，请咨询专业人士。
