# 字体改造方案（基于 Alpine Faction 源码实读）

结论先说：**比预想的乐观得多。FreeType 已经在里面了，改造集中在一个文件、约 200~300 行。**

> **进度：第一步（免编译的字体覆盖）已实测通过。**
> 2026-07-29，游戏内主菜单与 HUD 字幕均已换成思源黑体，`AlpineFaction.log` 零 ERROR，
> 四个字号（菜单 65/41/34、HUD 17）全部加载成功。
> 剩下的就是改 `gr_font.cpp` 让汉字真正显示。

依据文件：

- `game_patch/CMakeLists.txt`
- `game_patch/graphics/gr_font.cpp` ← 核心
- `game_patch/hud/hud.cpp`
- `game_patch/hud/hud_internal.h`

---

## 一、好消息：渲染管线本身没有障碍

`CMakeLists.txt` 里 `vendor/freetype` 已被包含并链接：

```cmake
target_include_directories(AlpineFaction PRIVATE ... ${CMAKE_SOURCE_DIR}/vendor/freetype/include ...)
target_link_libraries(AlpineFaction ... freetype ...)
```

`gr_font.cpp` 里的 `GrNewFont` 类已经实现了一套完整的现代字体管线：

- `FT_New_Memory_Face` 从内存加载 TTF
- `FT_Load_Char` + `FT_LOAD_RENDER` 逐字形栅格化
- `TextureAtlasPacker` 把字形打进纹理图集，**尺寸按需自动翻倍**（`try_pack` 失败就 `2 * atlas_size_` 重试）
- 图集上传为 `FORMAT_8888_ARGB` 位图，绘制时用 `rf::gr::bitmap_ex` 逐字形贴图

也就是说：**FreeType 能渲染任意码点，图集能自动长大，绘制路径不关心字符是什么。**
原版那个 221 字形的 `.vf` 位图字体限制，在 TTF 路径上根本不存在。

## 二、坏消息：卡点是死写的 Windows-1252 映射

`GrNewFont` 构造函数里：

```cpp
static std::pair<int, int> win_1252_char_ranges[]{
    {0x20, 0x7E}, {0x8C, 0x8C}, {0x95, 0x95}, ... {0xF9, 0xFC},
};
...
std::fill(char_map_, char_map_ + std::size(char_map_), -1);
for (auto& range : win_1252_char_ranges) {
    for (auto c = range.first; c < range.second + 1; ++c) {
        MultiByteToWideChar(1252, 0, &windows_1252_char, 1, &unicode_char, 1);
        ...
        char_map_[char_idx] = unicode_code_points.size() - 1;
    }
}
```

成员是 `int char_map_[256]` —— **单字节索引**。绘制时：

```cpp
for (auto ch : text) {                                    // 逐字节遍历
    auto glyph_idx = char_map_[static_cast<unsigned char>(ch)];
```

这就是 changelog 里 `Support ・ in TrueType fonts`、`Support © in TrueType fonts`
要一个字符一个字符加的原因 —— 那个 `win_1252_char_ranges` 表是手工维护的。

**所以限制不在渲染，而在"字节 → 字形"这一层映射。**

## 三、第二个卡点：普通 HUD 根本不走 TTF

`hud.cpp` 里：

```cpp
const char* hud_get_small_font_name(bool big)   { return big ? "regularfont.ttf:14" : "rfpc-small.vf"; }
const char* hud_get_default_font_name(bool big) { return big ? "regularfont.ttf:17" : "rfpc-medium.vf"; }
const char* hud_get_bold_font_name(bool big)    { return big ? "boldfont.ttf:26"    : "rfpc-large.vf"; }
```

**TTF 只在 "big HUD" 模式下启用**（需要 ≥1024x768），普通模式仍然走原版 `.vf` 位图字体。
而 `gr_init_font_hook` 明确写着：文件名以 `.vf` 结尾就原样交回引擎。

```cpp
if (string_ends_with(name, ".vf")) {
    return gr_init_font_hook.call_target(name, reserved);
}
```

对汉化的含义：**不改这三行，就只有开了 big HUD 才可能显示中文。**

## 四、改动清单

| # | 位置 | 改什么 | 量级 |
|---|---|---|---|
| 1 | `gr_font.cpp` 构造函数 | 用 `unordered_map<uint32_t,int>` 替掉 `char_map_[256]`；字符集不再硬编码，改为从字符集清单文件读取 | 中 |
| 2 | `gr_font.cpp` `draw()` / `get_size()` | 逐字节遍历改为 UTF-8 逐码点遍历 | 小 |
| 3 | `gr_font.cpp` `gr_fit_string()` | `text.pop_back()` 会切断多字节字符，改为按码点回退 | 小 |
| 4 | `hud.cpp` 三个 `hud_get_*_font_name` | 让普通 HUD 也走 TTF | 3 行 |
| 5 | `misc/ui.cpp` | 菜单字体路径，**尚未核实**，需要再读一遍 | 待定 |

字形数量不用全量预载。我们的译文用到多少汉字是确定的 —— 从 CSV 里扫一遍就有精确清单
（1929 条文本，估计 1500~2500 个不重复汉字）。按需生成字符集清单，正好契合
`TextureAtlasPacker` "构造时一次性打包"的现有设计，不用改成动态图集。

显存估算：2000 字形 @ 26px 粗体 ≈ 135 万像素 → 2048x2048 ARGB8888 ≈ 16 MB/字体，
三套字体约 30~50 MB。现代显卡无压力。真嫌大可以后续把图集改成 8 位 alpha。

## 五、字体文件本身不用改代码

`GrNewFont` 通过 `rf::File` 加载字体，走的是 packfile 系统。
也就是说，**在 `client_mods` 的 vpp 里放一个同名的 `regularfont.ttf` / `boldfont.ttf`
就能整体换成中文字体，一行代码都不用动。**

字体名格式是 `文件名:字号Y:字号X:标志`（`parse_font_name` 按 `:` 分割），
标志位 `d` 表示只要数字。

## 六、推荐路线

1. **先验证换字体**（已就绪，见下节）：做个只含中文 TTF 的 client_mods 包，开 big HUD 进游戏，
   看英文界面是否正常渲染。这一步不需要编译，能确认 packfile 覆盖链路通不通。
2. **再改字符集映射**：本地编译 Alpine，做改动 1~4，用几条中文测试串验证。
3. **然后决定上游还是 fork**：改动 1~3 是通用的多语言基础设施，不是中文特化，
   有相当大的机会被上游接受 —— README 里本来就写着支持 translation packs。
   走上游能免掉每次 Alpine 发版重新合并的长期负担。

改动 4 上游可能不愿意接（会影响所有人的 HUD 观感），那部分留在我们自己的补丁里，
或者做成开关。

## 六之一、第一步的测试包（已装好）

`tools/build_font.py` 用思源黑体/宋体（Noto Sans/Serif CJK SC）子集化生成两个字体，
打成 `rfcn_font.vpp`，已复制到 `<游戏目录>\client_mods\`。

```
regularfont.ttf   126 KB   Noto Sans CJK SC        ← 覆盖官方 45 KB 的
boldfont.ttf      179 KB   Noto Serif CJK SC Bold  ← 覆盖官方 32 KB 的
```

**粗体故意选了衬线体**：如果游戏里粗体标题变成衬线（横细竖粗、带笔锋），
就等于直接证明 `boldfont.ttf` 也被我们覆盖了 —— 这是个一眼可辨的探针，正式版会换回黑体。

字符集当前取自 `translation/test_charset.txt`（640 个码点，含拉丁 + 中文标点 + 测试汉字）。
加 `--full-cjk` 可以收录 CJK 基本区全部 20992 个汉字，代价是每个字体约 12 MB、
子集化耗时数分钟。正式版应该从译文里扫出精确字符集，而不是全量收录。

预期现象：**英文界面照常显示，但字形变了**（Noto 的拉丁字母和原版不同）。
中文这一步还不会出现 —— 引擎只栅格化 Windows-1252 那 200 多个字符，
要等改动 1~3 落地。

## 六之二、字号问题与 scale 杠杆（已验证）

第一步测试通过：换上我们的字体后游戏里字形明显变了，**`client_mods` 覆盖链路确认可用**。
但字变得很小。测量后找到原因 —— 官方字体 `OPTIEdgar-Extended` 是**扁宽体**：

| 17px 渲染 | 大写墨迹高 | "LOADING" 宽 |
|---|---|---|
| 官方 OPTIEdgar-Extended | 14.0 px | 117.8 px |
| 思源黑体 原始 | 13.0 px | 72.2 px（只有 61%） |
| 思源黑体 scale=1.5 | 19.0 px | 108.2 px |

高度只差 8%，**宽度差了 39%** —— 视觉上的"变小"主要来自占地面积，不是字高。

### scale 的实现原理

字号 `:17` 硬编码在 DLL 里，mod 改不了。但 FreeType 是按 `像素字号 ÷ unitsPerEm`
缩放轮廓的，所以：

**只改 `head.unitsPerEm`（CFF 字体同步改 `FontMatrix`），完全不动轮廓坐标。**

upem 从 1000 改成 667，轮廓还是按 1000 单位画的，渲染时就等比放大 1.5 倍，
字形、advance、行高全部一致放大。见 `tools/build_font.py` 的 `apply_scale()`。

这等于凭空多出一档 HUD 缩放，对 4K 用户很实用。

### 当前状态

```
client_mods/rfcn_font.vpp        scale=1.5   ← 已装
dist/client_mods/rfcn_font_x175.vpp  scale=1.75  ← 备选, 想试就替换
```

> **注意**：`client_mods` 里同时放两个包会一起加载，按字母序靠后的生效
> （`rfcn_font_x175.vpp` 会盖过 `rfcn_font.vpp`）。要换就只留一个。

## 六之三、踩到的坑：字体一直加载失败

第一次实测"字还是很小"，查 `logs\AlpineFaction.log` 才发现字体**根本没加载成功**：

```
[0.11] INFO : Opened packfile ...\client_mods\rfcn_font.vpp    ← 包读到了
[0.50] INFO : UI font sizes: 65 41 34
[0.50] ERROR: FT_New_Memory_Face failed: 2
[0.50] ERROR: Failed to load font boldfont.ttf:65: failed to load font
[0.50] ERROR: Failed to load font regularfont.ttf:41: failed to load font
[0.50] ERROR: Failed to load font regularfont.ttf:34: failed to load font
[0.53] ERROR: Failed to load font regularfont.ttf:17: failed to load font
```

FreeType 错误码 2 = `unknown file format`。**Alpine 内置的 FreeType 没编译 CFF 驱动**，
只认 glyf(TrueType) 轮廓；而思源黑体是 CFF(OpenType) 的。官方那两个字体查过了，都是 glyf。

修复分两步，缺一不可：

1. **CFF → glyf 轮廓转换**：用 `Cu2QuPen` 把三次贝塞尔转成二次，重建 `glyf`/`loca`，
   `maxp` 从 0.5 版升到 1.0 版补齐字段，删掉 `CFF `/`VORG`
2. **改文件头的 `sfntVersion`**：从 `'OTTO'`(0x4F54544F) 改成 `0x00010000`

第 2 步我一开始漏了，结果转换完 FreeType 仍然报错 —— 因为文件头还写着 OTTO，
FreeType 照旧走 CFF 分支，找不到 CFF 表就报 "table missing"。
**只有把两步都做完字体才能被识别。**

两个函数都在 `tools/build_font.py` 的 `otf_to_ttf()` 里，注释写清了为什么。

### 顺带确认的好消息

日志里 `UI font sizes: 65 41 34` 说明 **主菜单也走 TTF，而且字号随分辨率缩放**
（4K 下菜单用 65/41/34px，HUD 用 17px）。之前列为"未核实"的 `misc/ui.cpp` 那条可以划掉了 ——
菜单和 HUD 都在 TTF 路径上，中文改造一次覆盖两处。

## 六之四、纹理图集显存 —— 目前最大的隐患

多人游戏加载自定义地图时崩溃（`abnormal program termination`），根因是**字体图集吃光了地址空间**。

`RF_120na.exe` 是 2001 年的 **32 位程序，地址空间上限 2 GB**。而引擎构造字体时会把
**全部字形一次性栅格化进一张 ARGB8888 纹理**，边长向上取 2 的幂。

4K 分辨率下引擎会同时实例化 8 个字体（菜单 65/41/34px、HUD 17/13/11px、粗体 26/20px），
每个都带完整字符集：

| 字符集 | 图集总计 | 最大单个 |
|---|---|---|
| 1719 个码点（含整个中日韩标点区） | **440 MB** | 8192² = 256 MB |
| 1422 个码点（只收译文用到的） | **188 MB** | 4096² = 64 MB |

**关键在于 2 的幂的边界**：1719 个字形正好把 65px 那个字体顶过 4096² 的容量，
翻倍成 8192²，单张就是 256 MB。减到 1422 就落回 64 MB。

所以 `build_all.py` 现在**只收录译文里真正用到的字**。原先无脑收录整个中日韩标点区
（0x3000-0x303F、0xFF00-0xFFEF，共 300 多个码点），而译文实际只用到 11 个：
`、。《》！（），：；？`

`build_all.py` 每次构建都会打印预估值，超过 200 MB 会警告。

### 真正的解法：按需栅格化

现在的 188 MB 只是"能跑"，不是"合理"。根本问题是**一次性栅格化全部字形**：
菜单标题字体（65px）实际只会画到几十个不同的汉字，却为 1422 个都分配了空间。

正确做法是**用到哪个字才栅格化哪个**：预分配一张固定大小的图集，
绘制时遇到没见过的码点再生成并追加。这样每个字体的实际占用取决于它真正显示过的字，
估计能从 188 MB 降到 20~30 MB。

代价是要把 `TextureAtlasPacker` 从"构造时一次打包"改成动态分配，
并在绘制路径上做增量上传。这是个值得做但需要仔细测试的改动，**列为下一步**。

> **不缩放能省更多吗？** scale 从 1.5 降到 1.0 是 125 MB，只比 188 MB 少三分之一，
> 却要牺牲 4K 下的可读性。先留着 1.5，真不够用再动。

## 七、还没核实的

- Alpine 官方发布版是否链接了 Pure Faction 反作弊：`CMakeLists.txt` 显示
  `purefaction/pf_secret.cpp` 不存在时回退到 `pf_ac_stubs.cpp`，而该文件不在公开仓库里
- ~~`misc/ui.cpp` 里主菜单的字体选择逻辑~~ —— 已由日志确认走 TTF，字号 65/41/34

## 八、编译环境的现实

`CMakeLists.txt` 里写着 `target_compile_features(AlpineFaction PUBLIC cxx_std_23)`。

我这边的 Linux 沙箱只能装到 mingw-w64 的 **GCC 10.3**，不支持 C++23，
交叉编译基本没戏。所以改完代码要在别处编译，两条路：

1. **你本地用 Visual Studio 2022 编译**（`docs/BUILDING.md` 的官方路径）。
   我出补丁，你构建，产物是一个 `AlpineFaction.dll`，替换掉 Alpine 目录里那个即可。
2. **fork 到 GitHub 用 Actions 编译**。仓库里有 `.github/workflows`，
   推上去让 CI 出 DLL，不用配本地环境。顺带为将来推上游做准备。

不管走哪条，代码补丁我都能写好并说明每一处改动。
