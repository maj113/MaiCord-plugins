// Relationship Notifier: tells you when a friend removes you or withdraws a
// request, and when you lose a server or a group chat.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, friends, "Friends who remove you", true),
            (Toggle, requests, "Friend requests that are withdrawn", true),
            (Toggle, servers, "Servers you are no longer in", true),
            (Toggle, groups, "Group chats you are no longer in", true));

// "<before><name><after>" as a toast; a name that is empty becomes `fallback`.
static void tell(Ctx& ctx, Str before, Str name, Str fallback, Str after) {
    constexpr u32 kNameMax = 100;
    if (name.empty())
        name = fallback;
    if (name.bytes > kNameMax) {
        u32 cut = kNameMax;
        while (cut && (name[cut] & 0xC0) == 0x80) // not in the middle of a character
            --cut;
        name = name.sub(0, cut);
    }
    Text<MC_TOAST_TEXT_MAX> text;
    text.append(before);
    text.append(name);
    text.append(after);
    ctx.toast(text, Tone::warning);
}

static Str user_name(Ctx& ctx, const mc_event& e, Text<128>& scratch) {
    if (e.name.bytes)
        return Str(e.name);
    if (const auto user = ctx.read.user(e.user_id)) {
        scratch.append(user->name());
        return scratch;
    }
    return {};
}

static void on_relationship(Ctx& ctx, const ev::RelationshipRemove& e) {
    const Settings& s = ctx.settings();
    if (e.has(MC_EVENT_OWN))
        return;
    Text<128> scratch;
    if (e.value == MC_RELATIONSHIP_FRIEND && s.friends)
        tell(ctx, "", user_name(ctx, e, scratch), "Someone", " removed you as a friend");
    else if (e.value == MC_RELATIONSHIP_INCOMING && s.requests)
        tell(ctx, "", user_name(ctx, e, scratch), "Someone", " withdrew their friend request");
}

static void on_server(Ctx& ctx, const ev::GuildDelete& e) {
    if (ctx.settings().servers && !e.has(MC_EVENT_OWN))
        tell(ctx, "You are no longer in ", e.name(), "a server", " (you were removed, or it was deleted)");
}

static void on_channel(Ctx& ctx, const ev::ChannelDelete& e) {
    constexpr u64 kGroupDm = 3;
    if (ctx.settings().groups && e.value == kGroupDm && !e.has(MC_EVENT_OWN))
        tell(ctx, "You are no longer in ", e.name(), "a group chat", "");
}

MC_HOOKS(on_relationship, on_server, on_channel);
MC_PLUGIN(.owner = 0x6D63'7265'6C6E'6F74, .name = "Relationship Notifier", .version = "1.0.1",
          .summary = "Tells you when a friend removes you or you lose a server or group chat.");
