# 《红色派系》简体中文汉化

Red Faction（2001）的简体中文汉化与可重建工具，基于 Alpine Faction，提供译文、字体与字幕处理、引擎补丁和技术记录。

## 当前状态与支持版本

已发布 **v1.0**，包含核心汉化、中文标牌与过场字幕视频三个独立下载包。工程以 **Alpine Faction `v1.3.0_Bakeapple`** 为补丁基线，不将其他上游版本视为兼容。

仓库保存译文与源码，不包含完整游戏、游戏材质、视频或编译后的 DLL。运行与重建需要自行准备原版游戏资源。

## 下载 / 使用

[v1.0 发布页](https://github.com/jyh9521/Red-Faction-CN/releases/tag/v1.0)：

| 附件 | 内容 |
| --- | --- |
| `rfcn_core_v1.0.zip` | 核心汉化 |
| `rfcn_signage_v1.0.zip` | 中文标牌 |
| `rfcn_movies_v1.0.zip` | 带字幕的过场视频 |

玩家使用发布附件，不需要先编译源码。安装位置与所需组件按包内说明操作；覆盖前备份同名文件，恢复时还原备份并移除新增补丁文件。源码重建流程不是玩家安装流程。

## 技术摘要

项目对 Alpine Faction 的文字与界面路径进行修改，支持 Unicode 字形索引、UTF-8 解码、CJK 断行和独立语音字幕，并处理 Alpine 自身界面文本。字体基于 Noto Sans CJK SC 子集生成。

引擎改动与逆向结论见 [Alpine 改动](docs/ALPINE-CHANGES.md)、[差异记录](docs/ALPINE-DIFF.md)及[字体方案](docs/FONT-PLAN.md)。异常记录器的上游提交记录保存在 `upstream-pr-veh/`。

## 从源码重建

完整依赖、版本与操作见 [BUILDING.md](BUILDING.md)。主要步骤：

1. 准备 Alpine Faction `v1.3.0_Bakeapple` 源码与 Windows MSVC x86、CMake、Ninja 环境。
2. 应用并检查源码补丁：

   ```powershell
   python patches/apply_patch.py "D:\src\alpinefaction"
   python patches/apply_patch.py "D:\src\alpinefaction" --check
   ```

3. 按构建指南编译 `AlpineFaction.dll`。源码路径使用纯 ASCII。
4. 在 Linux 环境准备 Noto Sans CJK SC 与游戏的 `tables.vpp`、`maps_en.vpp`、`audio.vpp`，运行 `python tools/build_all.py` 生成本地化封包。

日常修订译文不需要重新运行语音识别；标牌与视频属于独立资源流程，不随核心封包自动重建。

## 仓库结构与文档

| 路径 | 内容 |
| --- | --- |
| `translation/` | 界面、剧情、语音、过场与视频字幕译文 |
| `patches/` | 引擎源码修改脚本与原因 |
| `tools/` | VPP、字体、TGA、标牌与构建工具 |
| `docs/` | 基线、技术笔记、对照与问题记录 |
| `upstream-pr-veh/` | 异常记录器的上游提交资料 |

- [重建指南](BUILDING.md)
- [补丁说明](patches/README.md)
- [基线记录](docs/BASELINE.md)
- [标牌术语表](docs/SIGNAGE-GLOSSARY.md)
- [第三方声明](NOTICES.md)

## 来源与许可

译文、转写与构建工具采用 [CC BY-SA 4.0](LICENSE)。对 [Alpine Faction](https://github.com/GooberRF/alpinefaction) 的修改遵循 [MPL-2.0](LICENSE-MPL-2.0.txt)，修改后的源码保存在 [rf-cn 分支](https://github.com/jyh9521/alpinefaction/tree/rf-cn)。

字体遵循 SIL OFL 1.1；标牌所用高清底图来自 Captain_Dagon 的放大包与 Goober 的重打包，详见第三方声明。原始游戏和商业资源归原权利人所有，不属于本项目译文与工具的授权范围。
