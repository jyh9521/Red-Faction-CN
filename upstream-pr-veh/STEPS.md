# 提交步骤

本地仓库 `<ALPINE_SRC>` 已经配好两个 remote：

- `origin` = GooberRF/alpinefaction（上游）
- `fork` = jyh9521/alpinefaction（你的 fork，上次提 PR 时建的）

当前是 detached HEAD 在 `v1.3.0_Bakeapple` 标签上，那 140 处汉化补丁就打在这份检出里。

**不要在这棵树上开 PR 分支**，否则汉化会跟着推上去。用 `git worktree` 另开一份独立
检出，原来这棵树一动不动。

## 1. 开一个干净的工作树

```cmd
cd /d <ALPINE_SRC>
git fetch origin
git worktree add ..\af-pr -b feat/exception-logger origin/master
cd ..\af-pr
```

> 从 `origin/master` 开分支，不是从你 fork 的 master —— fork 的 master 停在你上次
> 提 PR 的时候，已经落后了。这样开出来的分支自动是最新的，不用先同步 fork。

## 2. 放入新文件

```cmd
copy "<RF_CN>\upstream-pr-veh\exception_logger.cpp" game_patch\debug\
```

## 3. 三处一行改动

**`game_patch/debug/debug.h`**

```diff
 void debug_apply_patches();
 void debug_init();
+void exception_logger_init();
 void debug_cleanup();
```

**`game_patch/CMakeLists.txt`**

```diff
     debug/debug.cpp
+    debug/exception_logger.cpp
     debug/obj_debug.cpp
```

**`game_patch/main/main.cpp`** —— 放在模块初始化最前面，这样它能覆盖后续全部初始化过程：

```diff
     // Init modules
+    exception_logger_init();
     console_apply_patches();
```

## 4. 确认改动范围

提交前务必看一眼，**只应该有这 4 个文件**：

```cmd
git status --short
```

期望输出：

```
 M game_patch/CMakeLists.txt
 M game_patch/debug/debug.h
 M game_patch/main/main.cpp
?? game_patch/debug/exception_logger.cpp
```

多出任何别的文件就是串进了汉化改动，停下来检查。

## 5. 编译验证（可选）

代码和 build13 里验过的完全一致，这步主要是确认在干净的上游 master 上也能编过
（上游 master 可能比 v1.3.0 标签新）。

```cmd
"<VS_BUILDTOOLS>\VC\Auxiliary\Build\vcvarsall.bat" x86
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build > build.log 2>&1
findstr /n /c:"error" build.log
```

## 6. 提交推送

```cmd
git add game_patch/debug/exception_logger.cpp game_patch/debug/debug.h game_patch/CMakeLists.txt game_patch/main/main.cpp
git commit -m "Log first-chance exceptions that RF's own SEH swallows"
git push fork feat/exception-logger
```

推完 GitHub 会返回一个创建 PR 的链接，或者去
<https://github.com/GooberRF/alpinefaction/pulls> 点 New pull request。

- base：`GooberRF/alpinefaction` 的 `master`
- compare：`jyh9521/alpinefaction` 的 `feat/exception-logger`
- 正文用 `PR.md` 的内容

## 7. 收工

PR 合并（或关闭）之后再删，不然改不动了：

```cmd
cd /d <ALPINE_SRC>
git worktree remove ..\af-pr
```

原来那棵打了补丁的树全程没被碰过，不用恢复什么。可以顺手确认一下：

```cmd
python "<RF_CN>\patches\apply_patch.py" <ALPINE_SRC> --check
```
