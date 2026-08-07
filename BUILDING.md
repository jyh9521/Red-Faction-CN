# 重建指南

这份文档的目标：**半年后、换台电脑、只有这个仓库，也能把整个汉化重建出来。**

所以下面每一样外部依赖都写清楚了具体版本和来源。

---

## 一、外部依赖

仓库里没有这些，得自己准备。

### 1. Alpine Faction 源码

```
https://github.com/GooberRF/alpinefaction
tag: v1.3.0_Bakeapple
```

**补丁是按这个 tag 写的。** 换成 master 或更新的 tag，`apply_patch.py` 里会有一部分锚点匹配不上——脚本会明确告诉你是哪几处。

> 源码目录路径**必须是纯 ASCII**。带中文的路径会让 MSVC 的某些环节出问题。

### 2. 编译环境

- Visual Studio 2022 Build Tools，**x86** 工具链
- CMake + Ninja
- 实测用的是 MSVC toolset 14.44.35207

### 3. 中文字体：Noto Sans CJK SC

```
包名：fonts-noto-cjk（Debian/Ubuntu）
或：  https://github.com/notofonts/noto-cjk
版本：2.004
许可：SIL Open Font License 1.1
```

`tools/build_font.py` 里的路径是 Debian 的：

```
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc
```

换个系统的话改 `build_font.SOURCES` 就行。用的是 ttc 里的**索引 2**（简体中文）。

### 4. 游戏本体

需要 `tables.vpp`、`maps_en.vpp`、`audio.vpp` —— `build_all.py` 要从里面读原文做回填对照。

### 5. 高清标牌底图（只有重做标牌时才需要）

```
Captain_Dagon 的 ESRGAN 4x AI Upscale Pack（Goober 重新打包）
https://www.factionfiles.com/ff.php?action=file&id=7630
```

放进 `client_mods\`，然后 `python tools/signage.py extract-hd`。

**已经改好的 176 张中文标牌不在仓库里**，可以从发布的标牌包 `zz_rfcn_signage.vpp` 里取（`tools/vpp.py` 能解包）。

### 6. 语音识别模型（只有重做转写时才需要）

faster-whisper 格式，small 级别（int8 量化后约 460 MB）。
项目里放在 `rf_cn/asr-model/`。

```
pip install faster-whisper
```

日常改译文用不到它——转写结果已经落在 `translation/` 里了。

---

## 二、重建 DLL

```bat
python patches\apply_patch.py <ALPINE_SRC>
python patches\apply_patch.py <ALPINE_SRC> --check
```

`--check` 应该输出「142 条编辑全部可重复识别」。

然后编译：

```bat
"<VS_BUILDTOOLS>\VC\Auxiliary\Build\vcvarsall.bat" x86
cd /d <ALPINE_SRC>
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build > build.log 2>&1
findstr /n /c:"error" build.log
```

> **`findstr` 没有输出才算成功。** 别只看 cmake 最后一行——编译失败但链接没跑的时候，`build\bin\` 里会留着上一次的旧 DLL，很容易误以为成功了。

### 常用参数

| 参数 | 作用 |
|---|---|
| `--revert` | 撤销全部补丁（倒序执行） |
| `--check` | 只检查状态，不改文件 |
| `--no-veh` | 不装异常记录器。**出正式版时用这个** |
| `--no-ui-strings` | 不翻译 Alpine 自有的 UI 文本 |

---

## 三、重建 vpp

```bash
python tools/build_all.py --no-signage
```

### ⚠ 只能在 Linux 上跑

`build_all.py` 要从 Noto Sans CJK 的 `.ttc` 里做字体子集。Windows 上那些路径不存在，脚本会**静默跳过字体**——vpp 照样打得出来，只是里面没有中文字形。

装上去的表现是：**游戏里所有中文全部消失。** 不报错，就是没了。

正常的 `rfcn.vpp` 是 74 个文件、约 1.7 MB。缺字体的是 72 个、0.46 MB。
`tools/deploy.bat` 里加了体积检查，小于 1.2 MB 直接拒绝安装。

### 打标牌包

```bash
python tools/build_all.py
```

不加 `--no-signage` 就会顺带打 `zz_rfcn_signage.vpp`，前提是 `signage_hd/` 和 `work/signage_hd_orig/` 都在。

> `zz_` 前缀是必须的。引擎按文件名顺序加载 `client_mods`，后加载的覆盖先加载的，而常见的高清材质包叫 `Z_xxx.vpp`，里面也有这批标牌。

---

## 四、目录约定

`tools/` 里的脚本假设自己在 `<游戏目录>/rf_cn/tools/` 下，靠相对路径找：

```
rf_cn/
├── translation/      译文
├── patches/          补丁定义
├── tools/            工具
├── build/            输出（自动创建）
├── signage_hd/       改好的中文标牌（不在仓库里）
├── asr-model/        语音识别模型（不在仓库里）
└── work/
    ├── signage_hd_orig/   高清包原版，回封时的头部基准
    └── cutscene_audio/    过场音轨与识别结果
```

`GAME = os.path.dirname(ROOT)` —— 也就是说 `rf_cn` **必须放在游戏目录下**，脚本才找得到 `tables.vpp` 那些。

---

## 五、几个会浪费时间的坑

**注入的 C++ 必须是纯 ASCII。**
源码是 UTF-8 无 BOM，MSVC 在中文/日文系统上按系统代码页读它。注释里的汉字在 Shift-JIS 下会被当成双字节序列，行尾那个字的末字节是前导字节，会吃掉换行符——CRLF 时吃掉 `\r` 侥幸能编译，LF 时直接吃掉 `\n`，注释吞掉下一行。
要显示的中文一律用 `_v()` 转成 `\xNN` 转义。`apply_patch.py` 里有硬性检查。

**编辑定义里 `old` 不能是 `new` 的连续子串。**
否则打完补丁 `old` 仍然匹配得上，重跑就再插一遍——不报错，只是文件里悄悄多出重复的行。锚点往下多含一行就行。同样有硬性检查。

**`.bat` 文件不能含非 ASCII，也不能在 `if(...)` 块里展开带 `)` 的路径。**
前者：cmd 按系统 OEM 代码页读 `.bat`，UTF-8 中文直接破坏行解析。
后者：`Program Files (x86)` 里那个 `)` 会把 `if (` 块提前闭合，解析错误，窗口一闪就没。用 `goto` 标签代替。

**两个钩子挂同一个地址，后装的会悄悄顶掉先装的。**
Alpine 已经钩了不少函数。要加逻辑就搭它现成的钩子，别新开一个。
