// Member Count: how many members are online, and how many there are, above the member list.
// Inspired by Vencord's MemberCount.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Choice, show, "Show", 0, .items = {"Online and total", "Online only", "Total only"}),
            (Toggle, compact, "Abbreviate large counts", false, .description = "12.3K instead of 12,345."));

using Line = Text<MC_NODE_TOOLTIP_MAX>;

static void digits(Line& out, u32 n) {
    char buffer[10];
    u32 at = sizeof(buffer);
    do {
        buffer[--at] = static_cast<char>('0' + n % 10);
        n /= 10;
    } while (n);
    out.append(Str(buffer + at, sizeof(buffer) - at));
}

// 12,345 or, abbreviated, 12.3K and 1.2M.
static void count(Line& out, u32 n, bool abbreviate) {
    if (abbreviate && n >= 1000) {
        const u32 unit = n >= 1'000'000 ? 1'000'000 : 1000;
        const u32 whole = n / unit, tenth = n % unit / (unit / 10);
        digits(out, whole);
        if (whole < 100 && tenth) {
            out.push('.');
            digits(out, tenth);
        }
        out.push(unit == 1000 ? 'K' : 'M');
        return;
    }
    if (n >= 1000) {
        count(out, n / 1000, false);
        out.push(',');
        const u32 rest = n % 1000;
        if (rest < 100)
            out.push('0');
        if (rest < 10)
            out.push('0');
        digits(out, rest);
        return;
    }
    digits(out, n);
}

static void decorate(Ctx& ctx, const Header& header, Decoration& d) {
    if (!header.member_list() || !header.member_count)
        return;
    const Settings& s = ctx.settings();
    const bool online = s.show != 2 && header.online_count, total = s.show != 1 || !header.online_count;
    Line label, brief;
    Line* const lines[] = {&label, &brief};
    for (Line* line : lines) {
        const bool abbreviate = line == &brief || s.compact;
        if (online) {
            count(*line, header.online_count, abbreviate);
            line->append(" online");
        }
        if (online && total)
            line->append(" \xC2\xB7 ");
        if (total) {
            count(*line, header.member_count, abbreviate);
            line->append(" members");
        }
    }
    d.badge(badge(brief, Tone::neutral, {}, label));
}

MC_HOOKS(decorate);
MC_PLUGIN(.owner = 0x6D63'6D65'6D62'6374, .name = "Member Count", .version = "1.0.0",
          .summary = "Shows how many members are online and how many there are above the member list.",
          .api_level = 1);
