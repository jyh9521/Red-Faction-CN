Agreed. I've replaced the four code changes with the compiler flags — the PR is now a single
hunk in the root `CMakeLists.txt`:

```cmake
if(MSVC)
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
    add_compile_options(/arch:SSE2)
    # Pin both charsets. Sources are UTF-8; narrow string literals are Windows-1252,
    # because the .vf bitmap fonts are indexed by Windows-1252 byte value and several
    # literals embed those bytes directly (\x95 bullet, \xA6 chat prefix, ...).
    # Without this the ordinary literal encoding follows the build machine's system
    # code page: on a DBCS locale such as 932 those bytes become invalid multi-byte
    # sequences and std::format throws std::format_error at runtime.
    add_compile_options(/source-charset:utf-8 /execution-charset:windows-1252)
    # Statically link Microsoft's CRT.
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
else()
    add_compile_options(-msse2)
    add_compile_options(-finput-charset=UTF-8 -fexec-charset=WINDOWS-1252)
endif()
```

Two things I checked before proposing `/source-charset:utf-8`, since it changes how every
source file is read:

- All 486 non-vendor `.cpp`/`.h` files are valid UTF-8 today (86 of them contain non-ASCII
  bytes — mostly `·` and `×` in comments). So nothing gets misdecoded by pinning the source
  charset, and it also silences the C4819 warnings that currently appear on non-UTF-8 locales.
- `WINDOWS-1252` is a valid iconv name for GCC's `-fexec-charset`; `CP1252` works too if you
  prefer that spelling.

Worth noting the flags fix strictly more than the code changes did: `\xA6` and `\xA8` appear in
a number of other chat literals, and any future one is now safe by construction rather than
depending on someone remembering the rule.

Copilot's two comments are moot with this approach, since none of the three source files change
anymore. For the record, though:

- The per-legacy-client allocation it flagged in `af_broadcast_automated_chat_msg` is a real
  (small) inefficiency that predates this PR — the original `std::format("\xA6 {}", msg)` is
  inside the same player loop. Happy to open a separate PR hoisting it out if that's wanted.
- Its suggested comment wording ("MSVC validates narrow format strings as UTF-8") is not
  accurate: with `/utf-8` this exact literal compiles and runs fine and `0x95` passes through
  untouched. The trigger is specifically a double-byte ordinary literal encoding, where `0x95`
  is a lead byte with no valid trail byte after it. Measurements are in the main thread above.
