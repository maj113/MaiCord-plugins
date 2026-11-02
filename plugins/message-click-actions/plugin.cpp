// Message Click Actions: double-click your own message to edit it, double-click someone else's to reply,
// and optionally delete your messages with a modified click.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, edit, "Double-click your message to edit it", true),
            (Toggle, reply, "Double-click someone else's message to reply", true),
            (Toggle, ping, "Ping the author when replying", true, .visible_if = Setting::reply),
            (Choice, modifier, "Hold a key to double-click", 0, .items = {"Not needed", "Shift", "Ctrl", "Alt"},
             .description = "Double-clicks do nothing unless this key is down."),
            (Toggle, remove, "Delete your messages with a modified click", false,
             .description = "Use a key that double-clicks don't need, or the first click deletes."),
            (Choice, remove_key, "Delete with", 0,
             .items = {"Shift + click", "Ctrl + click", "Alt + click", "Ctrl + Shift + click"},
             .visible_if = Setting::remove),
            (Toggle, ask, "Ask before deleting", true, .visible_if = Setting::remove));

// The message waiting for a delete confirmation.
struct State {
    u64 channel, message;
};
MC_STATE(State, .version = 1);

static void remove(Ctx& ctx, u64 channel, u64 message) {
    switch (ctx.delete_message(channel, message)) {
    case MC_OK:
        break;
    case MC_E_RATE_LIMITED:
        ctx.toast("Slow down: too many deletes", Tone::warning);
        break;
    default:
        ctx.toast("Couldn't delete that message", Tone::warning);
    }
}

static void confirmed(Ctx& ctx, const ModalResult& result, u64 message) {
    const State& state = ctx.state<State>();
    if (result.accepted() && state.message == message)
        remove(ctx, state.channel, message);
}

// Whether this is a message people write: no joins, pins, local notices or tombstones.
static bool writable(const Message& message) {
    return !message.has(MC_MESSAGE_SYSTEM | MC_MESSAGE_LOCAL | MC_MESSAGE_DELETED);
}

static bool can_reply(Ctx& ctx, const Message& message) {
    const auto channel = ctx.read.channel(message.channel());
    return !channel || channel->has(MC_CHANNEL_CAN_SEND); // a channel the cache doesn't know: let the composer decide
}

static bool on_click(Ctx& ctx, const Message& message, const Click& click) {
    if (!writable(message))
        return false;
    const Settings& settings = ctx.settings();
    if (click.double_click()) {
        constexpr u32 kKeys[] = {0, MC_MOD_SHIFT, MC_MOD_CTRL, MC_MOD_ALT};
        if (settings.modifier && !click.with(kKeys[settings.modifier]))
            return false;
        if (message.own())
            return settings.edit && ctx.composer.edit(message.channel(), message.id()) == MC_OK;
        return settings.reply && can_reply(ctx, message) &&
               ctx.composer.reply(message.channel(), message.id(), settings.ping) == MC_OK;
    }
    constexpr u32 kChords[] = {MC_MOD_SHIFT, MC_MOD_CTRL, MC_MOD_ALT, MC_MOD_CTRL | MC_MOD_SHIFT};
    if (!settings.remove || !message.own() || click.modifiers != kChords[settings.remove_key])
        return false;
    if (!settings.ask) {
        remove(ctx, message.channel(), message.id());
        return true;
    }
    Modal modal{};
    modal.flags = MC_MODAL_DANGER;
    modal.title = Str("Delete this message?");
    modal.body = Str("This can't be undone.");
    modal.accept = Str("Delete");
    ctx.state<State>() = {message.channel(), message.id()};
    return ctx.modal<confirmed>(modal, message.id()) == MC_OK;
}

MC_HOOKS(mc::filter<on_click, MC_CLICK_FILTER_LEFT | MC_CLICK_FILTER_DOUBLE>);
MC_PLUGIN(.owner = 0x6D63'6D73'6763'6C6B, .name = "Message Click Actions", .version = "1.0.0",
          .summary = "Double-click to edit or reply to a message; click with a key held to delete yours.",
          .permissions = MC_PERM_COMPOSER | MC_PERM_ACT_MESSAGES, .api_level = 1);
