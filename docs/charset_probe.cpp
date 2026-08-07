// Minimal probe for the std::format_error reported in AlpineFaction issue #399.
//
// Build it three ways and compare:
//   cl /std:c++20 /EHsc charset_probe.cpp
//   cl /std:c++20 /EHsc /execution-charset:windows-1252 charset_probe.cpp
//   cl /std:c++20 /EHsc /utf-8 charset_probe.cpp
//
// The literal below is exactly what multi_scoreboard.cpp:180 uses. \x95 is the
// Windows-1252 bullet, which is not a valid UTF-8 lead byte.

#include <cstdio>
#include <format>
#include <stdexcept>

int main()
{
#ifdef _MSVC_EXECUTION_CHARACTER_SET
    std::printf("_MSVC_EXECUTION_CHARACTER_SET = %d\n", _MSVC_EXECUTION_CHARACTER_SET);
#else
    std::printf("_MSVC_EXECUTION_CHARACTER_SET = (not defined)\n");
#endif
    std::printf("_MSC_VER = %d, _MSVC_STL_UPDATE = %ld\n", _MSC_VER,
        static_cast<long>(_MSVC_STL_UPDATE));

    try {
        const std::string s = std::format("{} \x95 {}/{} PLAYING", "DEATHMATCH", 3, 8);
        std::printf("ok, %zu bytes:", s.size());
        for (unsigned char c : s) {
            std::printf(" %02X", c);
        }
        std::printf("\n");
    }
    catch (const std::format_error& e) {
        std::printf("std::format_error: %s\n", e.what());
        return 1;
    }
    return 0;
}
