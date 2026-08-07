**Describe the bug**

Four call sites pass format strings containing raw Windows-1252 bytes (`\x95`, `\xA6`) to
`std::format`. MSVC's `<format>` treats narrow strings as UTF-8 and validates the format string
accordingly; those bytes are invalid UTF-8 lead bytes, so `std::format` throws
`std::format_error`.

Two of the four are in the scoreboard draw path, so with a locally built DLL **the game
terminates a second or two after joining any multiplayer server**. Alpine's crash handler never
runs and `AlpineFaction.log` just stops mid-frame, because the exception is raised inside a
region covered by Red Faction's own `__try`/`__except`, which swallows it first.

This is not a recent regression in Alpine's logic — the literals have been there a while. It
became fatal as MSVC's `<format>` tightened format-string validation. The officially
distributed binaries do not show the problem on the same machine and the same server, so
presumably they were built with an older toolset; either way it only bites people building from
source.

Present on `master` (`b4e1e15`) and on tag `v1.3.0_Bakeapple`.

**To Reproduce**

1. Build `master` or `v1.3.0_Bakeapple` with MSVC toolset 14.44.35207, x86 Release.
2. Replace `AlpineFaction.dll` in a working install with the freshly built one. Change nothing
   else — no mods, stock settings, any server, any map.
3. Join a multiplayer server. The level finishes loading, then the process disappears the
   moment the scoreboard is first drawn. `AlpineFaction.log` ends mid-frame with no error line.
4. Put the officially distributed `AlpineFaction.dll` back and the problem goes away — which is
   what makes this look like a local build issue rather than a source bug.

**Expected behavior**

Joining a server works, and the scoreboard shows `DEATHMATCH • 3/8 PLAYING` as it does with the
official binaries.

**Screenshots**

Not applicable — the process exits, there is nothing on screen to capture.

For what it's worth, this is what an `AddVectoredExceptionHandler` hook reports. A VEH runs
ahead of any `__except` frame, so it sees the throw before RF swallows it:

```
C++ throw type = .?AVformat_error@std@@
what           = Invalid encoded character in format string.

stack:
    _CxxThrowException+0x67
    std::_Throw_format_error+0x1e
    std::_Parse_format_string<char, std::__p2286::_Format_handler<char>&>+0x17e
    std::__p2286::vformat_to<std::back_insert_iterator<std::string>>+0xb4
```

`_Parse_format_string` in that trace is the key detail: the fault is in the **format string**,
not in any argument.

**Environment (please complete the following information):**

- **OS:** Windows 11 x64, build 10.0.26100
- **Version:** Alpine Faction `master` @ `b4e1e15`, and tag `v1.3.0_Bakeapple`. Game is Red
  Faction 1.20 NA (Steam), English.
- **Toolchain:** MSVC toolset 14.44.35207 (VS 2022 Build Tools), x86, Release, Ninja generator
- **Relevant settings:** none — reproduces with default settings and no mods loaded. Big HUD on
  or off makes no difference, and it is independent of resolution and renderer settings.

**Additional context**

*Root cause*

`\x95` is the Windows-1252 bullet (`•`) and `\xA6` the broken bar (`¦`). Both are meaningful to
the engine's `.vf` bitmap fonts, which are indexed by Windows-1252 byte value, so storing them
as raw bytes is correct for rendering. They are not valid UTF-8, though, and MSVC's `<format>`
requires the format string to be.

The same bytes are perfectly safe as **arguments** or in plain concatenation — no decoding
happens there. The bug is specifically about the format string.

*Affected sites*

| File | `master` | `v1.3.0_Bakeapple` | Literal |
|---|---|---|---|
| `game_patch/hud/multi_scoreboard.cpp` | 180 | 149 | `"{} \x95 {}/{} PLAYING"` |
| `game_patch/hud/multi_scoreboard.cpp` | 208 | 177 | `"{1} \x95 {0:%Y} ({2}) by {3}"` |
| `game_patch/multi/multi.cpp` | 706 | 653 | `"\xA6 Shot canceled: {}"` |
| `game_patch/multi/alpine_packets.cpp` | 2636 | 1764 | `"\xA6 {}"` |

The two scoreboard sites are what makes multiplayer unplayable — they run on every scoreboard
draw. The other two are server-side chat paths and only fire when hosting.

`alpine_packets.cpp` already builds the very same `\xA6 ` prefix by concatenation 47 lines below
the broken one, and that version is fine:

```cpp
// line 2683 - fine
std::string legacy_msg = std::string("\xA6 ") + std::string(msg);

// line 2636 - throws
send_chat_line_packet(std::format("\xA6 {}", msg), &player);
```

*Suggested fix*

Keep the bytes — they are what the bitmap fonts expect — and move them out of the format
string. Rendering stays byte-for-byte identical.

`game_patch/hud/multi_scoreboard.cpp`. The two sites sit in separate block scopes, so the
constant needs file scope. `<string_view>` is not currently included in this file, so a plain
`const char*` avoids adding an include:

```diff
 constexpr float ENTER_ANIM_MS = 100.0f;
 constexpr float LEAVE_ANIM_MS = 100.0f;
+
+// Windows-1252 bullet. Must stay a raw byte for the .vf bitmap fonts, and must stay out
+// of any std::format format string, which has to be valid UTF-8.
+constexpr const char* SEPARATOR = "\x95";
```

```diff
     const std::string game_info = std::format(
-        "{} \x95 {}/{} PLAYING",
+        "{} {} {}/{} PLAYING",
         multi_game_type_name_upper(game_type),
+        SEPARATOR,
         multi_num_spawned_players(),
         rf::multi_num_players()
     );
```

```diff
     std::string level_info = std::format(
-        "{1} \x95 {0:%Y} ({2}) by {3}",
+        "{1} {4} {0:%Y} ({2}) by {3}",
         std::chrono::sys_seconds{
             std::chrono::seconds{rf::level.level_timestamp}
         },
         rf::level.name,
         rf::level.filename,
-        rf::level.author
+        rf::level.author,
+        SEPARATOR
     );
```

`game_patch/multi/multi.cpp`:

```diff
-    auto message = std::format("\xA6 Shot canceled: {}", reason);
+    auto message = std::string("\xA6 Shot canceled: ") + reason;
```

`game_patch/multi/alpine_packets.cpp`:

```diff
-            send_chat_line_packet(std::format("\xA6 {}", msg), &player);
+            send_chat_line_packet(std::string("\xA6 ") + std::string(msg), &player);
```

The last two match the concatenation style already used elsewhere in the same file.

Please do **not** fix these by converting the literals to UTF-8 (`\xe2\x80\xa2` and friends).
`\xA6` in particular is a wire-visible chat prefix that peers match with `string_istarts_with`,
so changing the bytes would break protocol compatibility; and with the stock Windows-1252
bitmap fonts a UTF-8 bullet would render as three garbage glyphs.

I am happy to put these four changes up as a PR if that is useful.

*Two things that might be worth a follow-up*

Finding these by grep is harder than it looks. The obvious pattern only catches half of them:

```
git grep -nE 'format\("[^"]*\\x[89a-fA-F]' -- '*.cpp' '*.h'
```

finds the two chat sites but misses both scoreboard sites, because there the literal sits on the
line after `std::format(`. Searching for high-byte escapes in any string literal:

```
git grep -noE '"[^"]*\\x[89a-fA-F][0-9a-fA-F][^"]*"' -- '*.cpp' '*.h'
```

returns 27 hits, most of which are perfectly fine — chat prefixes built by
concatenation, and byte patterns in `network.cpp` that are x86 machine code for `memcmp`
assertions rather than text. Only four are format strings. Some cheap guard against
reintroducing the pattern might be worth it, since eyeballing does not scale here.

Separately: a C++ exception thrown anywhere under the render loop currently vanishes without a
log entry, because RF's own SEH catches it first. A vectored exception handler installed at
startup — even one that only logs and returns `EXCEPTION_CONTINUE_SEARCH` — would have turned
this from a multi-day hunt into a single log line.
