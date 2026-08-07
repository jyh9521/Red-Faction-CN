# Log first-chance exceptions that RF's own SEH swallows

Follow-up to the last point in #399.

## Problem

Red Faction wraps large parts of the frame loop in its own `__try`/`__except`. When an
exception is raised in there, `AlpineFaction.log` simply stops mid-frame — no error line,
no stack, nothing. `crash_handler_stub` uses `SetUnhandledExceptionFilter`, which by
definition only runs for exceptions nobody handled, so it never sees these either.

That is what made #399 take days to track down. The process vanished a second after
joining any server and the log ended mid-frame. The bug turned out to be a
`std::format_error` thrown deep under the scoreboard draw path — completely invisible
until I attached a vectored exception handler by hand.

## What this adds

`game_patch/debug/exception_logger.cpp`, ~250 lines, self-contained.

A vectored exception handler runs ahead of every SEH frame, so it observes the throw
before RF can eat it. For C++ throws (`0xE06D7363`) and access violations (`0xC0000005`)
it logs:

- the exception type, demangled from the MSVC throw metadata, plus `what()` when the
  thrown object derives from something in `namespace std`
- for access violations: read/write/execute, the faulting address, and the PC
- a stack trace

Everything else is passed through untouched.

Reverting the #400 fix locally and joining a server reproduces the original crash. This
is the actual log output, and it is the whole of what the log used to contain for this
crash — nothing:

```
[  11.97] INFO: [exception-logger] dbghelp: sym=true line=true walk=true tbl=true base=true
[  11.97] WARN: [first-chance 1] C++ throw type=.?AVformat_error@std@@ what=Invalid encoded character in format string.
[  12.00] WARN: [first-chance 1]   stack:
    RaiseException+0x64
    _CxxThrowException+0x67 [D:\a\_work\1\s\src\vctools\crt\vcruntime\src\eh\throw.cpp:79]
    std::_Throw_format_error+0x1e
    std::_Parse_format_string<char,std::__p2286::_Format_handler<char> &>+0x17e
    std::__p2286::vformat_to<std::back_insert_iterator<std::basic_string<char,std::char_traits<char>,std::allocator<char> > > >+0xb4
    std::__p2286::vformat<0>+0xc2
    draw_scoreboard_header+0x154
    draw_scoreboard_internal_new+0x770
    RF_120na.exe+0x70873
```

The log ends there — the process dies immediately after. Note the last three frames:
the trace walks out of the CRT and through Alpine's own functions to name
`draw_scoreboard_header` as the call site, then hits RF's own code where there are no
symbols and degrades to `module+RVA`. Landing on the exact function is what makes the
output actionable; when I hit this by hand in #399 the trace stopped at `vformat_to`
and I still had to find the call site myself.

## Design notes

**Behaviour is unchanged.** The handler only logs and always returns
`EXCEPTION_CONTINUE_SEARCH`. It never handles, swallows or alters an exception.

**These are first-chance exceptions.** Most are caught and handled a moment later, and
seeing them in the log is normal — there are ~60 `catch` sites in the tree. They are
logged at `warn`, not `error`, and the message says `first-chance` so a log reader does
not mistake them for crashes. Output is capped at 40 entries per session, so a hot loop
that throws cannot flood the file.

**No build system changes beyond the new source file.** dbghelp is resolved at runtime
with `LoadLibrary`/`GetProcAddress`, so there is no new link dependency and nothing
breaks if it is unavailable — symbol resolution just degrades to `module+RVA`.

**MinGW.** Everything except the C++ type-name probe is plain Win32 and builds either
way. That probe is `#ifdef _MSC_VER` for two independent reasons: the `0xE06D7363`
exception code and the `ThrowInfo` structures it walks are the MSVC C++ ABI, so on a
GCC build it would be parsing something that isn't there; and walking them safely needs
`__try`/`__except`, which GCC does not have. Under MinGW a C++ throw is still logged
with its stack, just without the type name. Access violations are unaffected.

**Stack walking.** Release x86 omits frame pointers, so a naive EBP walk stops after a
few frames. `StackWalk64` uses the FPO/unwind data from the PDB and gets the whole
chain; if dbghelp could not be loaded it falls back to
`RtlCaptureStackBackTrace`. Symbols resolve to `func+off [file:line]` when a PDB is
next to the module, otherwise `module+RVA`, which is still enough to locate a frame in
a disassembler.

**Reading the throw metadata is guarded.** `probe_throw` walks the MSVC `ThrowInfo`
structures and, for `std::` types, calls `what()` through the vtable. That is all
pointer-chasing into a process that is already in trouble, so it sits inside a
`__try`/`__except` and reports `<probe faulted>` rather than making a bad situation
worse. It deliberately contains no objects with destructors, otherwise MSVC rejects the
`__try` with C2712.

## Things you may want to change

- **Always on vs opt-in.** It is on by default here, since the whole point is to have
  the line already in the log when someone reports a mystery crash rather than asking
  them to reproduce it. If the first-chance noise bothers you, gating it behind a
  command line switch or an `alpine_settings.ini` option is a two-line change.
- **The 40-entry cap and the 28-frame depth** are arbitrary; adjust to taste.

## Testing

Built with MSVC toolset 14.44.35207, x86 Release, Ninja. Played through single player
and joined multiplayer servers.

On a clean tree the log is quiet — a normal session produces no first-chance entries at
all, so this does not add noise in practice.

To confirm it actually fires, I reverted the #400 fix, rebuilt, and joined a server.
That produced the output quoted above, and the game crashed exactly as it did in #399 —
behaviour is unchanged, the exception is simply recorded on its way past.
