# Alpine Faction 装了什么、动了什么

原始比对表：[ALPINE-DIFF.md](ALPINE-DIFF.md)（`snapshots/00-vanilla.json` → `snapshots/01-alpinefaction.json`）

**一句话结论：它对游戏目录几乎是零侵入 —— 原版文件一个都没被改写。**

---

## 一、游戏目录的改动：新增 3 个，改动 1 个

| 文件 | 大小 | 性质 |
|---|---|---|
| `RF_120na.exe` | 1.7 MB | **新增**。英文 1.20 NA 版游戏主程序，Alpine 实际启动的是它 |
| `RedFaction.exe.bak` | 6.1 MB | **新增**。原版启动器的备份 |
| `RED.exe.manifest` | 627 B | **新增**。给关卡编辑器补的 Common-Controls 6.0 清单 |
| `RedFaction.exe` | — | **改为符号链接**，指向 Alpine 的启动器 |

关键的几点：

- **`RF.exe` 没有被动过**（哈希不变）。我原先预计它会被就地替换成 1.20 版，实际是**另起一个 `RF_120na.exe`**，原版 exe 原封不动。
- **所有 `.vpp` 一个都没改**，`tables.vpp`、`levels*.vpp`、`ui.vpp` 全部保持原样。德文版那种"就地改 tables.vpp 导致多人不可用"的坑，Alpine 从设计上就避开了。
- `build.ver` 仍是 177，Steam 的版本标识没被篡改。
- `RedFaction.exe` 变成符号链接，就是 README 里说的"让 Steam 的开始游戏按钮直接拉起 Alpine"。原件保留为 `.bak`，随时可还原。

> 顺带修了工具一个 bug：快照原本直接跳过符号链接，导致 `RedFaction.exe` 在第一次比对里
> 显示成"被删除"。现在符号链接会单独记录并在报告里标注指向。

## 二、Alpine Faction 自身：10 个文件，28.9 MB

装在 `<ALPINE_DIR>`，和游戏目录完全分离。

| 文件 | 大小 | 说明 |
|---|---|---|
| `alpinefaction.vpp` | 13.0 MB | 资源包，250 个文件 |
| `AlpineFaction.dll` | 5.9 MB | 游戏补丁本体（注入 `RF_120na.exe`） |
| `unins000.exe` + `.dat` | 3.5 MB | 卸载程序 |
| `AlpineFactionLauncher.exe` | 2.8 MB | 启动器 |
| `AlpineEditor.dll` | 1.7 MB | 关卡编辑器补丁 |
| `CrashHandler.exe` | 1.2 MB | 崩溃处理器 |
| `d3d8to9.dll` | 842 KB | D3D8 → D3D9 转换层 |
| `LICENSE.txt` / `licensing-info.txt` | 40 KB | MPL-2.0 及第三方许可 |

`alpinefaction.vpp` 里是 103 tga、47 ogg、33 tbl、27 awp（bot 寻路点）、14 bin、12 v3m、5 vbm、4 wav、**2 ttf**、1 vf、1 v3c、1 txt。

## 三、对汉化最重要的发现

`alpinefaction.vpp` 里确实躺着源码里那两个字体文件：

```
     45712  regularfont.ttf
     31896  boldfont.ttf
     36324  biggerfont.vf
```

45 KB 和 32 KB —— 是纯拉丁字符的小字体。中文字体通常 5~15 MB，体积上完全放得下。

结合之前读源码的结论和 RF Wiki 记载的加载顺序：

```
1. 根目录标准 vpp
2. alpinefaction.vpp          ← 字体在这里
...
6. client_mods 里的 vpp       ← 我们的汉化包放这里，优先级更高
```

**我们只要在 `client_mods` 的 vpp 里放一个同名 `regularfont.ttf`，就能覆盖掉它的字体，不用改一行代码。**
这正好是 [FONT-PLAN.md](FONT-PLAN.md) 里"第一步免编译验证"要做的事。

## 四、对整合发布的影响

原先担心的"要不要重新分发一个被改过的 `RF.exe`"这个问题，形态变了但没消失：

- 好的一面：Alpine 不覆盖原版 exe，用户的 Steam 文件完整无损，校验/重装都不受影响
- 仍需考虑：`RF_120na.exe` 是官方 1.20 程序打补丁得来的，整合包要不要带它，
  和直接分发 `RF.exe` 是同一类问题。最稳妥是**不带**，让用户自己跑 Alpine 官方安装器，
  我们只发汉化包（`client_mods` 里的 vpp + 中文字体）

按这个思路，汉化整合包的体积可能只有 **十几 MB**（主要是中文字体），而不是几百 MB。

## 五、下一步

1. 你先启动一次 Alpine，确认菜单能点、窗口模式正常（原来那个独占全屏卡死的问题应该没了）
2. 启动后我再做一次快照 —— 首次运行会生成 `alpine_settings.ini`，还会把你原来的
   `players.cfg` 导入过去，这些都该进忽略名单
3. 然后做免编译的字体覆盖验证
