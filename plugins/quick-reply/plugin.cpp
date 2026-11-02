// Quick Reply: two keys walk the reply target up and down the open channel's messages.
// Inspired by Vencord's QuickReply.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Keybind, older, "Reply to the previous message", MC_KEY(0x26, MC_KEY_CTRL)),   // Ctrl + Up
            (Keybind, newer, "Reply to the next message", MC_KEY(0x28, MC_KEY_CTRL)),       // Ctrl + Down
            (Toggle, ping, "Ping the author", true),
            (Toggle, skip_own, "Skip your own messages", true),
            (Toggle, skip_bots, "Skip bots", false));

static bool wanted(const Settings& settings, const mc_message_ref& message) {
    if (message.flags & (MC_MESSAGE_SYSTEM | MC_MESSAGE_LOCAL | MC_MESSAGE_DELETED))
        return false;
    return !(settings.skip_own && (message.flags & MC_MESSAGE_OWN)) &&
           !(settings.skip_bots && (message.flags & MC_MESSAGE_BOT));
}

// The closest wanted message older than `from` (0: from the newest); 0 when the loaded history has none.
static u64 before(Ctx& ctx, u64 channel, u64 from) {
    mc_message_ref page[MC_READ_MESSAGES_MAX];
    for (u32 pass = 0; pass < 4; ++pass) {
        const u32 count = ctx.read.messages(channel, from, page);
        for (u32 i = 0; i < count; ++i)
            if (wanted(ctx.settings(), page[i]))
                return page[i].message_id;
        if (count < MC_READ_MESSAGES_MAX)
            break;
        from = page[count - 1].message_id;
    }
    return 0;
}

// The closest wanted message newer than `from`; 0 when `from` is the newest or isn't in the loaded history.
static u64 after(Ctx& ctx, u64 channel, u64 from) {
    if (!from)
        return 0;
    mc_message_ref page[MC_READ_MESSAGES_MAX];
    u64 closest = 0, below = 0;
    for (u32 pass = 0; pass < 4; ++pass) {
        const u32 count = ctx.read.messages(channel, below, page);
        for (u32 i = 0; i < count; ++i) {
            if (page[i].message_id == from)
                return closest;
            if (wanted(ctx.settings(), page[i]))
                closest = page[i].message_id;
        }
        if (count < MC_READ_MESSAGES_MAX)
            break;
        below = page[count - 1].message_id;
    }
    return 0;
}

static void pressed(Ctx& ctx, const KeybindPressed& key) {
    const auto open = ctx.read.open_channel();
    if (!open || open->edit_id)
        return;
    const bool up = key.index == static_cast<u32>(Setting::older);
    const u64 target = up ? before(ctx, open->channel_id, open->reply_to) : after(ctx, open->channel_id, open->reply_to);
    if (!target) {
        // Down from the newest message drops the reply.
        if (!up && open->reply_to && ctx.composer.clear_reply(open->channel_id) == MC_OK)
            return;
        ctx.toast(up ? Str("No earlier message to reply to") : Str("No later message to reply to"));
        return;
    }
    if (ctx.composer.reply(open->channel_id, target, ctx.settings().ping) == MC_OK)
        ctx.composer.focus();
    else
        ctx.toast("Can't reply here", Tone::warning);
}

MC_HOOKS(pressed);
MC_PLUGIN(.owner = 0x6D63'716B'7270'6C79, .name = "Quick Reply", .version = "1.0.0",
          .summary = "Ctrl+Up and Ctrl+Down pick the message you reply to.", .permissions = MC_PERM_READ_MESSAGES | MC_PERM_COMPOSER,
          .api_level = 2);
