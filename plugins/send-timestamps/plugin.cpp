// Send Timestamps: a chat-bar button that turns a date and time you type into a
// Discord timestamp (<t:1762370000:f>) in your composer, shown in each reader's
// own time zone and language.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Choice, format, "Format", 4,
             .items = {"Short time", "Long time", "Short date", "Long date", "Short date/time", "Long date/time",
                       "Relative"},
             .description = "Preselected in the dialog; it remembers what you pick."));

constexpr char kStyles[] = "tTdDfFR";
constexpr mc_str kFormats[] = {MC_S("Short time (16:20)"),  MC_S("Long time (16:20:30)"),
                               MC_S("Short date (20/04/2021)"), MC_S("Long date (20 April 2021)"),
                               MC_S("Short date/time"),      MC_S("Long date/time"),
                               MC_S("Relative (in 2 hours)")};

// ---- Dates -----------------------------------------------------------------------

// Days since 1970-01-01 of a civil date, and back (proleptic Gregorian).
static i64 days_from_civil(i64 y, i64 m, i64 d) {
    y -= m <= 2;
    const i64 era = (y >= 0 ? y : y - 399) / 400, yoe = y - era * 400;
    const i64 doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1, doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}
struct Civil {
    i64 year, month, day;
};
static Civil civil_from_days(i64 z) {
    z += 719468;
    const i64 era = (z >= 0 ? z : z - 146096) / 146097, doe = z - era * 146097;
    const i64 yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365, doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const i64 mp = (5 * doy + 2) / 153, month = mp < 10 ? mp + 3 : mp - 9;
    return {yoe + era * 400 + (month <= 2), month, doy - (153 * mp + 2) / 5 + 1};
}
static i64 floor_div(i64 a, i64 b) {
    return a / b - (a % b < 0);
}
static bool valid_day(i64 y, i64 m, i64 d) {
    const bool leap = y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    const i64 days[] = {31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    return m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1];
}

template <u32 N> static void put_number(Text<N>& out, u64 value, u32 width = 0) {
    char digits[20];
    u32 count = 0;
    do {
        digits[count++] = static_cast<char>('0' + value % 10);
        value /= 10;
    } while (value);
    for (u32 i = count; i < width; ++i)
        out.push('0');
    while (count)
        out.push(digits[--count]);
}

// "YYYY-MM-DD HH:MM" at unix_seconds shifted by the user's offset.
static void put_local(Text<24>& out, i64 unix_seconds, i32 offset) {
    const i64 local = unix_seconds + offset, days = floor_div(local, 86400), rest = local - days * 86400;
    const Civil date = civil_from_days(days);
    put_number(out, static_cast<u64>(date.year), 4);
    out.push('-');
    put_number(out, static_cast<u64>(date.month), 2);
    out.push('-');
    put_number(out, static_cast<u64>(date.day), 2);
    out.push(' ');
    put_number(out, static_cast<u64>(rest / 3600), 2);
    out.push(':');
    put_number(out, static_cast<u64>(rest % 3600 / 60), 2);
}

// ---- Reading what the user typed -----------------------------------------------------

struct Cursor {
    Str s;
    u32 at = 0;
    bool end() const {
        return at >= s.size();
    }
    bool eat(char c) {
        const bool found = !end() && s[at] == c;
        at += found;
        return found;
    }
    void skip_spaces() {
        while (eat(' ')) {
        }
    }
    // Between min and max digits.
    bool number(u32 min, u32 max, i64& out) {
        u32 count = 0;
        i64 value = 0;
        for (; at + count < s.size() && count < max && s[at + count] >= '0' && s[at + count] <= '9'; ++count)
            value = value * 10 + (s[at + count] - '0');
        out = value;
        at += count >= min ? count : 0;
        return count >= min;
    }
};

// "2026-11-05 18:30[:15]", "2026-11-05" (midnight) or "18:30" (today), then nothing, Z, UTC or
// +HH[:MM] / -HH[:MM]; without a zone it's the user's own time.
static bool parse_when(Ctx& ctx, Str text, i64& unix_seconds) {
    Cursor c{text.trimmed()};
    i64 y = 0, m = 0, d = 0, hour = 0, minute = 0, second = 0;
    const u32 start = c.at;
    const bool dated = c.number(4, 4, y) && (c.eat('-') || c.eat('/')) && c.number(1, 2, m) &&
                       (c.eat('-') || c.eat('/')) && c.number(1, 2, d);
    if (!dated) {
        c.at = start;
        const i64 now = static_cast<i64>(ctx.now_ms() / 1000);
        if (!now)
            return false;
        const Civil today = civil_from_days(floor_div(now + ctx.local_offset(now), 86400));
        y = today.year, m = today.month, d = today.day;
    }
    c.skip_spaces();
    c.eat('T');
    c.skip_spaces();
    const bool timed = !c.end() && c.number(1, 2, hour);
    if (timed && !(c.eat(':') && c.number(2, 2, minute) && (!c.eat(':') || c.number(2, 2, second))))
        return false;
    if ((!dated && !timed) || !valid_day(y, m, d) || hour > 23 || minute > 59 || second > 59 || y < 1970 || y > 9999)
        return false;
    const i64 wall = days_from_civil(y, m, d) * 86400 + hour * 3600 + minute * 60 + second;
    c.skip_spaces();
    const bool zoned = !c.end();
    i64 east = 0;
    if (zoned && !(c.eat('Z') || c.eat('z') || (c.s.sub(c.at).equals_ascii_nocase("utc") && (c.at += 3)))) {
        const bool west = c.s[c.at] == '-';
        i64 zone_hour = 0, zone_minute = 0;
        if (!(c.eat('+') || c.eat('-')) || !c.number(1, 2, zone_hour) || zone_hour > 14)
            return false;
        c.eat(':');
        c.number(2, 2, zone_minute);
        if (zone_minute > 59)
            return false;
        east = (zone_hour * 3600 + zone_minute * 60) * (west ? -1 : 1);
    }
    c.skip_spaces();
    if (!c.end())
        return false;
    unix_seconds = wall - east;
    if (!zoned) { // the user's own zone, whose offset depends on the date
        unix_seconds = wall - ctx.local_offset(wall);
        unix_seconds = wall - ctx.local_offset(unix_seconds);
    }
    return unix_seconds >= 0;
}

// ---- The dialog ----------------------------------------------------------------------

static void answered(Ctx& ctx, const ModalResult& result, u64);

static void ask(Ctx& ctx, Str initial, u32 format) {
    Modal modal{};
    modal.has_input = 1;
    modal.title = Str("Insert a timestamp");
    modal.body = Str("In your time zone: 2026-11-05 18:30, or 18:30 for today. End with Z for UTC or +02:00 for another zone.");
    modal.accept = Str("Insert");
    modal.input_label = Str("Date and time");
    modal.input_initial = initial;
    modal.input_hint = Str("YYYY-MM-DD HH:MM");
    modal.input_max_chars = 40;
    modal.select_label = Str("Format");
    modal.select_items = kFormats;
    modal.select_count = sizeof(kFormats) / sizeof(kFormats[0]);
    modal.select_initial = format;
    ctx.modal<answered>(modal);
}

static void answered(Ctx& ctx, const ModalResult& result, u64) {
    if (!result.accepted())
        return;
    ctx.set_setting(Setting::format, result.selected());
    i64 when = 0;
    if (!parse_when(ctx, result.text(), when)) {
        ctx.toast("Use YYYY-MM-DD HH:MM, or HH:MM for today", Tone::warning);
        ask(ctx, result.text(), result.selected()); // the gesture of the answer carries over
        return;
    }
    Text<32> stamp;
    stamp.append("<t:");
    put_number(stamp, static_cast<u64>(when));
    stamp.push(':');
    stamp.push(kStyles[result.selected() < sizeof(kStyles) - 1 ? result.selected() : 4]);
    stamp.push('>');
    ctx.composer.insert(stamp);
}

MC_BUTTON(stamp, surface::chat_bar, "Insert timestamp", "lucide/calendar") {
    Text<24> now;
    if (const i64 seconds = static_cast<i64>(ctx.now_ms() / 1000))
        put_local(now, seconds, ctx.local_offset(seconds));
    ask(ctx, now, ctx.settings().format);
}

MC_PLUGIN(.owner = 0x6D63'736E'6474'696D, .name = "Send Timestamps", .version = "1.0.0",
          .summary = "Inserts a Discord timestamp from a date and time you type.", .permissions = MC_PERM_COMPOSER);
