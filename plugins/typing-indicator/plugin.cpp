// Typing Indicator: a dots icon on channel, DM and server icons where someone is typing; hover for who.
// Inspired by Vencord's TypingIndicator.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, channels, "Channels and DMs", true),
            (Toggle, servers, "Server icons", true),
            (Toggle, muted, "Include muted channels and servers", false),
            (Toggle, blocked, "Include blocked users", false),
            (Toggle, names, "Name who is typing in the tooltip", true));

// Whoever sent a typing notice in the last kHold seconds. The tick counts seconds and runs only while
// somebody is listed, so nothing runs when nobody is typing.
struct Entry {
    u64 user, channel, guild;
    u32 until, reserved;
};
constexpr u32 kMax = 32, kHold = 10;
constexpr u64 kClock = 1;
struct State {
    u32 tick, count;
    Entry list[kMax];
};
MC_STATE(State, .version = 1);

static void drop(Ctx& ctx, State& st, u32 at) {
    ctx.invalidate_channel(st.list[at].channel);
    if (st.list[at].guild)
        ctx.invalidate_guild(st.list[at].guild);
    st.list[at] = st.list[--st.count];
}

static void typed(Ctx& ctx, const ev::Typing& e) {
    if (e.has(MC_EVENT_OWN) || !e.user_id || !e.channel_id)
        return;
    State& st = ctx.state<State>();
    u32 at = 0;
    while (at < st.count && !(st.list[at].user == e.user_id && st.list[at].channel == e.channel_id))
        ++at;
    if (at == st.count) { // new: take a free slot, else the one that expires first
        if (st.count == kMax) {
            at = 0;
            for (u32 i = 1; i < kMax; ++i)
                if (st.list[i].until < st.list[at].until)
                    at = i;
            drop(ctx, st, at);
        }
        at = st.count++;
        st.list[at] = {e.user_id, e.channel_id, e.guild_id, 0, 0};
        if (st.count == 1)
            ctx.timer(kClock, 1000, true);
        ctx.invalidate_channel(e.channel_id);
        if (e.guild_id)
            ctx.invalidate_guild(e.guild_id);
    }
    st.list[at].until = st.tick + kHold;
}

// Sending a message ends the typing.
static void sent(Ctx& ctx, const ev::MessageCreate& e) {
    State& st = ctx.state<State>();
    for (u32 i = 0; i < st.count; ++i)
        if (st.list[i].user == e.user_id && st.list[i].channel == e.channel_id) {
            drop(ctx, st, i);
            break;
        }
    if (!st.count)
        ctx.cancel_timer(kClock);
}

static void tick(Ctx& ctx, const Timer&) {
    State& st = ctx.state<State>();
    ++st.tick;
    for (u32 i = 0; i < st.count;)
        if (st.list[i].until <= st.tick)
            drop(ctx, st, i);
        else
            ++i;
    if (!st.count)
        ctx.cancel_timer(kClock);
}

static void number(Text<MC_NODE_TOOLTIP_MAX>& out, u32 n) {
    char digits[10];
    u32 at = sizeof(digits);
    do {
        digits[--at] = static_cast<char>('0' + n % 10);
        n /= 10;
    } while (n);
    out.append(Str(digits + at, sizeof(digits) - at));
}

// The tooltip for the people typing in one channel (channel != 0) or one server; false when nobody counts.
static bool who(Ctx& ctx, u64 channel, u64 guild, Text<MC_NODE_TOOLTIP_MAX>& tip) {
    const Settings& s = ctx.settings();
    const State& st = ctx.state<State>();
    Str first, second;
    u32 count = 0;
    for (u32 i = 0; i < st.count; ++i) {
        const Entry& e = st.list[i];
        if (channel ? e.channel != channel : e.guild != guild)
            continue;
        const auto user = ctx.read.user(e.user, e.guild);
        if (user && user->relationship == MC_RELATIONSHIP_BLOCKED && !s.blocked)
            continue;
        if (!channel && !s.muted) {
            const auto where = ctx.read.channel(e.channel);
            if (where && where->has(MC_CHANNEL_MUTED))
                continue;
        }
        if (count < 2)
            (count == 0 ? first : second) = user ? user->name() : Str("Someone");
        ++count;
    }
    if (!count)
        return false;
    if (s.names) {
        if (count == 1) {
            tip.append(first);
            tip.append(" is typing\xE2\x80\xA6");
        } else {
            tip.append(first);
            tip.append(count == 2 ? Str(" and ") : Str(", "));
            tip.append(second);
            if (count > 2) {
                tip.append(" and ");
                number(tip, count - 2);
                tip.append(count == 3 ? Str(" other") : Str(" others"));
            }
            tip.append(" are typing\xE2\x80\xA6");
        }
    }
    if (!s.names || tip.overflowed()) { // a long name falls back to the plain wording
        tip.clear();
        tip.append(count == 1 ? Str("Someone is typing\xE2\x80\xA6") : Str("Several people are typing\xE2\x80\xA6"));
    }
    return true;
}

static void decorate_channel(Ctx& ctx, const Channel& channel, Decoration& d) {
    Text<MC_NODE_TOOLTIP_MAX> tip;
    if (ctx.settings().channels && (!channel.has(MC_CHANNEL_MUTED) || ctx.settings().muted) &&
        who(ctx, channel.id(), 0, tip))
        d.badge(badge("\xE2\x80\xA6", Tone::accent, "lucide/pencil", tip)); // the row shows a text pill; the tooltip names them
}

static void decorate_guild(Ctx& ctx, const Guild& guild, Decoration& d) {
    Text<MC_NODE_TOOLTIP_MAX> tip;
    if (ctx.settings().servers && (!(guild.flags & MC_GUILD_MUTED) || ctx.settings().muted) &&
        who(ctx, 0, guild.id(), tip))
        d.badge(icon("lucide/ellipsis", tip, Tone::accent));
}

// A setting changes what the cached decorations say.
static void changed(Ctx& ctx, const SettingChanged&) {
    ctx.invalidate_channel(0);
    ctx.invalidate_guild(0);
}

MC_HOOKS(typed, sent, tick, decorate_channel, decorate_guild, changed);
MC_PLUGIN(.owner = 0x6D63'7479'7069'6E64, .name = "Typing Indicator", .version = "1.0.0",
          .summary = "Marks the channels, DMs and servers where someone is typing.", .api_level = 1);
