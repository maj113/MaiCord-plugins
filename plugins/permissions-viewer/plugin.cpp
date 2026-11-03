// Permissions Viewer: right-click a member to see which permissions they have in the server and how this
// channel changes them, or a channel to see what you can do there.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Choice, show, "Show", 0, .items = {"Every permission", "Moderation and management only"}),
            (Toggle, channel, "Show how the channel changes them", true,
             .description = "Adds what the channel's overwrites grant or take away."));

constexpr u32 kBox = 2000; // what the read-only text holds

struct Permission {
    Str name;
    u8 bit;
};
// In Discord's order: general, membership, text, voice, then events.
constexpr Permission kPermissions[] = {
    {"View Channels", 10},         {"Manage Channels", 4},        {"Manage Roles", 28},
    {"Create Expressions", 43},    {"Manage Expressions", 30},    {"View Audit Log", 7},
    {"Manage Webhooks", 29},       {"Manage Server", 5},          {"View Server Insights", 19},
    {"View Creator Analytics", 41}, {"Create Invite", 0},          {"Change Nickname", 26},
    {"Manage Nicknames", 27},      {"Kick Members", 1},           {"Ban Members", 2},
    {"Timeout Members", 40},       {"Send Messages", 11},         {"Send Messages in Threads", 38},
    {"Create Public Threads", 35}, {"Create Private Threads", 36}, {"Embed Links", 14},
    {"Attach Files", 15},          {"Add Reactions", 6},          {"Use External Emoji", 18},
    {"Use External Stickers", 37}, {"Mention Everyone", 17},      {"Manage Messages", 13},
    {"Pin Messages", 51},          {"Bypass Slowmode", 52},       {"Manage Threads", 34},
    {"Read Message History", 16},  {"Send Text-to-Speech", 12},   {"Use Application Commands", 31},
    {"Send Voice Messages", 46},   {"Create Polls", 49},          {"Use External Apps", 50},
    {"Connect", 20},               {"Speak", 21},                 {"Video", 9},
    {"Use Activities", 39},        {"Use Soundboard", 42},        {"Use External Sounds", 45},
    {"Use Voice Activity", 25},    {"Priority Speaker", 8},       {"Mute Members", 22},
    {"Deafen Members", 23},        {"Move Members", 24},          {"Set Voice Channel Status", 48},
    {"Request to Speak", 32},      {"Create Events", 44},         {"Manage Events", 33},
};
constexpr u64 bit(u32 index) {
    return 1ull << index;
}
constexpr u64 kAdministrator = bit(3);
// What lets someone change the server or other people's experience of it.
constexpr u64 kPowerful = bit(1) | bit(2) | bit(4) | bit(5) | bit(7) | bit(13) | bit(17) | bit(22) | bit(23) |
                          bit(24) | bit(27) | bit(28) | bit(29) | bit(30) | bit(33) | bit(34) | bit(40);

// One permission per line, each after prefix. False when bits names none of them.
static bool lines(Text<kBox>& out, u64 bits, Str prefix) {
    bool any = false;
    for (const Permission& permission : kPermissions) {
        if (!(bits & bit(permission.bit)))
            continue;
        out.append(prefix);
        out.append(permission.name);
        out.push('\n');
        any = true;
    }
    return any;
}

// The server-wide permissions, then (when the channel differs) what it adds and removes, in a read-only
// information dialog.
static void show(Ctx& ctx, Str who, u64 guild, u64 channel, u64 server_bits, u64 channel_bits) {
    if (!server_bits) {
        ctx.toast("MaiCord doesn't know this member's roles yet", Tone::warning);
        return;
    }
    const u64 mask = ctx.settings().show == 1 ? kPowerful : ~0ull;
    Text<kBox> text;
    if (server_bits & kAdministrator)
        text.append("Administrator: every permission, in every channel\n");
    else if (!lines(text, server_bits & mask, {}))
        text.append("None of these\n");
    if (ctx.settings().channel && channel && channel_bits && !(server_bits & kAdministrator) &&
        channel_bits != server_bits) {
        const auto info = ctx.read.channel(channel);
        text.append("\nIn ");
        text.append(info ? info->name() : Str("this channel"));
        text.append(" (+ adds, - removes)\n");
        const bool added = lines(text, channel_bits & ~server_bits & mask, "+ ");
        if (!lines(text, server_bits & ~channel_bits & mask, "- ") && !added)
            text.append("No change to these\n");
    }
    text.set_size(text.size() - 1); // the last line break
    Text<256> body;
    body.append(who);
    if (const auto info = ctx.read.guild(guild)) {
        body.append(" in ");
        body.append(info->name());
    }
    Modal modal{};
    modal.flags = MC_MODAL_INFO | MC_MODAL_READ_ONLY;
    modal.has_input = 1;
    modal.title = Str("Permissions");
    modal.body = body.view();
    modal.input_label = ctx.settings().show == 1 ? Str("Moderation and management") : Str("Granted");
    modal.input_initial = text.view();
    if (ctx.modal(modal) != MC_OK)
        ctx.toast("Couldn't open the viewer", Tone::warning);
}

// -- The menus ------------------------------------------------------------------------

static bool in_server(Ctx&, const MenuTarget& target) {
    return target.guild_id != 0;
}

MC_MENU(of_member, menu::user, "View permissions", .visible = in_server) {
    const auto user = ctx.read.user(target.user_id, target.guild_id);
    show(ctx, user ? user->name() : Str("This member"), target.guild_id, target.channel_id,
         ctx.read.permissions(target.guild_id, 0, target.user_id),
         target.channel_id ? ctx.read.permissions(target.guild_id, target.channel_id, target.user_id) : 0);
}

// What you can do in a channel: your server-wide permissions and the channel's overwrites on them.
MC_MENU(of_channel, menu::channel, "View my permissions here", .visible = in_server) {
    const auto channel = ctx.read.channel(target.channel_id);
    const auto guild = ctx.read.guild(target.guild_id);
    if (!channel || !guild) {
        ctx.toast("MaiCord doesn't have this channel yet", Tone::warning);
        return;
    }
    show(ctx, "You", target.guild_id, target.channel_id, guild->self_permissions, channel->self_permissions);
}

MC_PLUGIN(.owner = 0x6D63'7065'726D'7677, .name = "Permissions Viewer", .version = "1.1.0",
          .summary = "Shows what a member or you can do in a server and a channel.", .api_level = 3);
