# Alpine Faction 中文支持补丁

让引擎能显示汉字。打完补丁重新编译 `AlpineFaction.dll` 即可。

## 一、拿源码

```
git clone https://github.com/GooberRF/alpinefaction.git
cd alpinefaction
```

你现在装的是 **1.3.0 (Bakeapple)**。如果想和当前版本对齐而不是跟 master，
先 `git tag` 看一眼再 `git checkout <对应 tag>`。补丁是按字符串匹配的，
master 上大概率也能打上；匹配不到会明确报错，不会静默改坏。

## 二、打补丁

```
python <本目录>\apply_patch.py <alpinefaction 源码目录> --big-hud-only-off
```

> **已在实际 checkout 上验证过**（`v1.3.0_Bakeapple-48-gb4e1e15b`，2026-07-29）：
> 11 处全部匹配成功，打→再打→撤销→再撤销四轮幂等，撤销后文件回到 ASCII，
> 换行保持 CRLF 不变。

- 不加 `--big-hud-only-off`：只在 Big HUD 模式下显示中文（普通 HUD 仍用位图字体）
- 加上：普通 HUD 也切到 TTF，两种模式都能显示中文

脚本可重复执行，已打过的会跳过；`--revert` 撤销。往返一致性我测过，撤销后与原文件逐字节相同。

## 三、编译

**不需要 CMake GUI。** 官方 `docs/BUILDING.md` 提到的 GUI 只是一种方式，
而且用它还得手动把平台从 x64 改成 Win32，容易漏。
下面这套是照着项目自己的 CI（`.github/workflows/ci.yml` 的 `build-msvc`）来的，
用命令行反而更省事、更不容易出错。

### 1. 装 Visual Studio 2022 Community（免费）

<https://visualstudio.microsoft.com/zh-hans/downloads/>

安装时勾选工作负载 **「使用 C++ 的桌面开发」**。
再切到「单个组件」标签，确认勾上 **「适用于 Windows 的 C++ CMake 工具」** ——
这一项会顺带装好 `cmake` 和 `ninja`，省得单独去装。

> 版本要够新。`game_patch` 用了 C++23 的 deducing-this
> （CI 里注释写着"GCC 14 MinGW required for C++23 deducing-this"），
> 太老的 VS2022 编不过。装最新版即可。

### 2. 打开 x86 命令提示符

开始菜单里找 **「x86 Native Tools Command Prompt for VS 2022」**。

**必须是 x86 那个**，不能用 x64 或普通 cmd。Alpine 只能编 32 位，
`CMakeLists.txt` 开头就写着不是 4 字节指针就直接 `FATAL_ERROR`。
用这个命令提示符就等于 CI 里的 `-Arch x86`，不用再操心平台参数。

### 3. 编译

```bat
cd /d <ALPINE_SRC>
mkdir build
cd build
cmake .. -G Ninja -D CMAKE_BUILD_TYPE=Release
cmake --build . -j
```

第一次编译要几分钟。

### 4. 产物位置

`CMakeLists.txt` 里 `CMAKE_RUNTIME_OUTPUT_DIRECTORY` 设的是 `${CMAKE_BINARY_DIR}/bin`，
所以东西在：

```
build\bin\AlpineFaction.dll
```

## 四、替换 DLL

把编译出的 `AlpineFaction.dll` 覆盖到：

```
<ALPINE_DIR>\AlpineFaction.dll
```

**先把原文件备份**（改个名留着），出问题好回滚。

## 五、验证

游戏启动后看 `<游戏目录>\logs\AlpineFaction.log`，应该出现：

```
INFO: Loaded 490 extra glyphs from alpine_extra_charset.txt
```

数字对得上就说明扩展字符集读到了。然后把 `translation/` 里翻译几条，
`python tools\build_mod.py` 打包，进游戏看中文。

---

## 补丁改了什么

全部在 `game_patch/graphics/gr_font.cpp` 和 `game_patch/hud/hud.cpp` 里，共 8 处
（加 `--big-hud-only-off` 是 11 处）。

| # | 位置 | 改动 |
|---|---|---|
| G2 | gr_font.cpp | **`.vf` 位图字体重定向到 TTF** |
| U | ui.cpp | **Alpine 自有 UI 文本汉化**（73 条，来自 `alpine_ui.tsv`） |
| A | gr_font.cpp | 补 `<cstdint>` / `<string_view>` 头文件 |
| B | gr_font.cpp | `int char_map_[256]` → `unordered_map<uint32_t,int>` |
| C | gr_font.cpp | 新增 `utf8_decode()` 和 `get_extra_charset()` |
| D | gr_font.cpp | 构造函数：字符集加入扩展汉字，**同时按字节值和码点注册** |
| E | gr_font.cpp | `draw()` 逐字节 → 逐码点 |
| F | gr_font.cpp | `get_size()` 逐字节 → 逐码点 |
| G | gr_font.cpp | `gr_fit_string()` 按码点回退 |
| H | hud.cpp | `hud_fit_string()` 按码点回退 |
| I~K | hud.cpp | *(可选)* 普通 HUD 也用 TTF |

### 两个值得说明的设计

**D 处为什么要注册两种键。** 原版 `strings.tbl` 是 Windows-1252 编码，
高位字节（如 `ü` = 0xFC）是单字节；我们汉化后的 tbl 是 UTF-8，同一个字符是两字节。
解决办法是**两种键都往 `char_map_` 里塞**：字节值 0xFC 和码点 U+00FC 都指向同一个字形。

这样能成立，是因为 0x80–0xFF 在 UTF-8 里本来就是非法起始字节，我们的解码器遇到它们
会原样返回字节值。所以两套编码可以并存，**德文版和法文版不会被这个补丁破坏** ——
这一点对将来推上游很重要。

**C 处的字符集从哪来。** 引擎在构造字体时一次性把所有字形打进纹理图集，
所以必须提前知道要哪些字。补丁会从 packfile 里找 `alpine_extra_charset.txt`
（UTF-8 文本，只看里面出现过哪些字符），由汉化包提供。
文件不存在时行为和原版完全一致，不影响没装汉化的用户。

`tools/build_font.py` 会自动把这个文件和字体一起打进 vpp。

### 实际打补丁时踩到的两个坑

**CRLF。** Windows 上 git checkout 出来的源码是 CRLF，而补丁里的字符串是 LF，
第一次预检 11 处全部匹配失败。脚本现在会读入时归一化成 LF、写回时还原原有换行风格，
所以不会制造无谓的全文件 diff。

**注入源码的注释必须是纯 ASCII。** 最初写的是中文注释，会有两个麻烦：

- MSVC 读没有 BOM 的源文件时按系统代码页解释，中文 Windows 上是 GBK。
  UTF-8 的中文会被误读，而 GBK 的某些第二字节正好是 `0x5C`（反斜杠）——
  出现在 `//` 注释里就变成了行继续符，会把下一行整个吞掉，编译报莫名其妙的错。
- 就算不出错，中文注释也不可能被上游接受。

现在所有注入源码的内容都是英文，脚本里有自检确保这一点。补丁打完源文件仍是 ASCII。

### G2：为什么还要重定向 `.vf` 字体

Alpine 的 `menu_init_hook` 只把 `rf::ui` 的四个全局字体换成了 TTF，
但部分 UI 控件（**武器自动切换优先级列表**、**按键绑定列表**）持有独立的字体句柄，
仍然请求 `.vf` 位图字体。位图字体按单字节索引字形，UTF-8 的每个字节都被当成一个
Latin 字符画出来 —— `装填` 渲染成 `è£…å¡«`。

补丁在字体加载入口把三个通用文本字体重定向：

| 原字体 | 目标 | 字号 |
|---|---|---|
| `rfpc-large.vf` | `boldfont.ttf` | `scale_y × 14.5` |
| `rfpc-medium.vf` | `regularfont.ttf` | `scale_y × 9.0` |
| `rfpc-small.vf` | `regularfont.ttf` | `scale_y × 7.5` |

系数直接沿用 Alpine 自己 `menu_init_hook` 里的那套，所以字号和它的 UI 字体一致。

**`bigfont.vf` / `smallfont.vf` / `biggerfont.vf` 故意不动** —— 那三个只有 32~69 个字形、
`first_ascii` 非标准（7 和 5），是 HUD 计数器的专用字形集，不是通用文本，改了会坏。

### U：Alpine 自有 UI 文本

`ADVANCED` 面板、`Environment Sounds Multiplier`、`Mouse scale` 这些是 Alpine 自己加的界面，
**硬编码在 `misc/ui.cpp` 的 C++ 字符串字面量里**，不在 `strings.tbl`，翻译流程碰不到。

译文放在 [`alpine_ui.tsv`](alpine_ui.tsv)（两列：英文、中文），补丁脚本自动生成替换。
译文留空或与英文相同的条目会跳过（比如 `DirectInput` 保持原样）。

**两个必须处理的编码陷阱**：

1. **源码必须保持纯 ASCII**，所以中文写成 `\xNN` 转义。
   直接写中文的话，MSVC 在中文/日文 Windows 上按系统代码页解释无 BOM 源文件，
   GBK 的某些第二字节正好是 `0x5C`（反斜杠），出现在字符串里会变成转义符。
2. **C++ 的十六进制转义是贪婪的**：`"\xe5F"` 会被当成一个超大转义值而不是 `\xe5` + `F`。
   所以转义后面紧跟十六进制数字字符时，必须断开成相邻字面量 `"\xe5" "F"`，编译期自动拼接。
   74 条里有 1 条触发了这个情况（`输入新的视场值（0 为自动缩放）：` 里的 `0`）。

`c_escape()` 处理了这两点，并有往返验证（模拟 C++ 的「先按字面量边界切分、
各自解析转义、最后拼接」顺序）。

> 这条规则不是纸上谈兵：我第一版验证脚本把顺序写反了（先拼接再解析），
> 结果 `\xef\xbc\x88` + `0` 被解析成 `\x880` = 2176 越界报错。
> 报错本身恰好证明了断开是必需的。

**代价**：Alpine 每次更新 `ui.cpp` 变了，这部分可能要重做。
补丁按字符串精确匹配，匹配不到会明确报错，不会静默失效。

### 已知的取舍

图集是"构造时一次性打包"的，字形多了会吃显存。粗略估算 2000 个汉字：

| 字号 | 图集尺寸 | 显存 |
|---|---|---|
| 17px (HUD) | 1024² | 4 MB |
| 34px / 41px (菜单) | 2048² | 各 16 MB |
| 65px (菜单粗体) | 4096² | 67 MB |

合计约 100 MB。现代显卡吃得下，但不算漂亮。更好的做法是**按需栅格化**
（用到哪个字才生成哪个），代价是要把图集改成动态分配。这一版先不做，
正式版的字符集应该从译文里精确扫出来，而不是收录全部 CJK。
