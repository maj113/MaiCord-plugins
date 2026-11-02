// Server Info: a "Server info" item in a server's context menu that lists what MaiCord knows about it.
// Inspired by Vencord's ServerInfo.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, ids, "Show IDs", true, .description = "The server's ID and its owner's."));

using Body = Text<512>; // the dialog's text

static void number(Body& out, u64 value) {
    char buffer[20];
    u32 count = 0;
    do {
        buffer[count++] = static_cast<char>('0' + value % 10);
        value /= 10;
    } while (value);
    while (count)
        out.push(buffer[--count]);
}
static void two_digits(Body& out, u64 value) {
    out.push(static_cast<char>('0' + value / 10 % 10));
    out.push(static_cast<char>('0' + value % 10));
}
// "YYYY-MM-DD" for a day count since 1970-01-01 (proleptic Gregorian calendar).
static void date(Body& out, u64 days_since_epoch) {
    const i64 days = static_cast<i64>(days_since_epoch) + 719'468;
    const i64 era = days / 146'097;
    const i64 doe = days - era * 146'097;
    const i64 yoe = (doe - doe / 1'460 + doe / 36'524 - doe / 146'096) / 365;
    const i64 doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const i64 mp = (5 * doy + 2) / 153;
    const i64 month = mp < 10 ? mp + 3 : mp - 9;
    number(out, static_cast<u64>(yoe + era * 400 + (month <= 2 ? 1 : 0)));
    out.push('-');
    two_digits(out, static_cast<u64>(month));
    out.push('-');
    two_digits(out, static_cast<u64>(doy - (153 * mp + 2) / 5 + 1));
}
// "3 years", "5 months" or "12 days": how long ago, roughly.
static void age(Body& out, u64 days) {
    const u64 years = days / 365, months = days / 30;
    const u64 count = years ? years : months ? months : days;
    number(out, count);
    out.append(years ? Str(" year") : months ? Str(" month") : Str(" day"));
    if (count != 1)
        out.push('s');
}
// Text cut to at most `limit` bytes on a character boundary.
static Str shortened(Str text, u32 limit) {
    u32 bytes = text.bytes < limit ? text.bytes : limit;
    while (bytes < text.bytes && bytes && (static_cast<u8>(text[bytes]) & 0xC0) == 0x80)
        --bytes;
    return text.sub(0, bytes);
}
static void line(Body& out, Str label, u64 value) {
    out.append(label);
    number(out, value);
    out.push('\n');
}

constexpr Str kVerification[] = {"None", "Low", "Medium", "High", "Very high"};
constexpr u64 kAdministrator = 1ull << 3;
// The permission bits Discord defines: not bit 47, nothing past bit 53.
constexpr u64 kPermissionBits = ((1ull << 54) - 1) & ~(1ull << 47);

static void copy_id(Ctx& ctx, const ModalResult& result, u64 guild) {
    if (!result.accepted())
        return;
    Body id;
    number(id, guild);
    if (ctx.copy(id) != MC_OK)
        ctx.toast("Couldn't copy the ID", Tone::warning);
}

MC_MENU(info, menu::guild, "Server info") {
    const auto guild = ctx.read.guild(target.guild_id);
    if (!guild) {
        ctx.toast("MaiCord doesn't have this server yet", Tone::warning);
        return;
    }
    const bool ids = ctx.settings().ids;
    Body body;
    body.append(shortened(guild->name(), 80));
    body.append("\n\n");
    if (ids)
        line(body, "ID: ", guild->id());

    // A server's ID starts with its creation time: 42 bits of milliseconds since 2015-01-01.
    const u64 created = (guild->id() >> 22) + 1'420'070'400'000;
    const u64 now = ctx.now_ms();
    const i64 local = static_cast<i64>(created) + i64{ctx.local_offset(static_cast<i64>(created / 1000))} * 1000;
    body.append("Created: ");
    date(body, static_cast<u64>(local) / 86'400'000);
    if (now > created) {
        body.append(" (");
        age(body, (now - created) / 86'400'000);
        body.append(" ago)");
    }
    body.push('\n');

    const auto owner = ctx.read.user(guild->owner_id, guild->id());
    body.append("Owner: ");
    body.append(owner ? shortened(owner->name(), 40) : Str("unknown"));
    if (owner && owner->self())
        body.append(" (you)");
    if (ids) {
        body.append(" · ");
        number(body, guild->owner_id);
    }
    body.push('\n');

    if (guild->member_count) {
        body.append("Members: ");
        number(body, guild->member_count);
        if (guild->online_count) {
            body.append(" (");
            number(body, guild->online_count);
            body.append(" online)");
        }
        body.push('\n');
    }
    // The counts below are 0 when MaiCord doesn't have them.
    const struct {
        Str label;
        u32 count;
    } counts[] = {{"Channels: ", guild->channel_count}, {"Roles: ", guild->role_count}, {"Emoji: ", guild->emoji_count}};
    Str separator;
    for (const auto& item : counts) {
        if (!item.count)
            continue;
        body.append(separator);
        body.append(item.label);
        number(body, item.count);
        separator = Str(" · ");
    }
    if (!separator.empty())
        body.push('\n');
    if (guild->channel_count) {
        body.append("Verification: ");
        body.append(kVerification[guild->verification_level < 5 ? guild->verification_level : 0]);
        body.push('\n');
    }
    if (guild->boost_count) {
        body.append("Boosts: ");
        number(body, guild->boost_count);
        body.append(" (level ");
        number(body, guild->boost_tier);
        body.append(")\n");
    }

    body.append("You can: ");
    if (guild->self_permissions & kAdministrator) {
        body.append("everything (administrator)");
    } else {
        number(body, static_cast<u64>(__builtin_popcountll(guild->self_permissions & kPermissionBits)));
        body.append(" permissions server-wide");
    }
    if ((guild->flags & MC_GUILD_MUTED))
        body.append("\nMuted");
    if (guild->mention_count) {
        body.push('\n');
        number(body, guild->mention_count);
        body.append(guild->mention_count == 1 ? Str(" unread mention") : Str(" unread mentions"));
    }

    Modal modal{};
    modal.title = Str("Server info");
    modal.body = body.view();
    modal.accept = Str("Copy ID");
    modal.cancel = Str("Close");
    if (ctx.modal<copy_id>(modal, guild->id()) != MC_OK)
        ctx.toast("Couldn't open the server info", Tone::warning);
}

MC_PLUGIN(.owner = 0x6D63'7372'7669'6E66, .name = "Server Info", .version = "1.0.0",
          .summary = "Shows a server's age, owner, size and boosts from its context menu.",
          .permissions = MC_PERM_CLIPBOARD, .api_level = 2);
