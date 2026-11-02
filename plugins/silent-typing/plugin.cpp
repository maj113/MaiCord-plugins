// Silent Typing: stops MaiCord from telling a channel that you're typing.
// A chat-bar toggle and /silent_typing switch it; the setting does too.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, silent, "Don't send typing notices", true),
            (Toggle, button, "Show a button in the chat bar", true));

static void show(Ctx& ctx, bool silent, bool button);

MC_BUTTON(keys, surface::chat_bar, "Silent typing", "lucide/keyboard", .toggle = true) {
    const bool next = !ctx.settings().silent;
    ctx.set_setting(Setting::silent, next);
    show(ctx, next, ctx.settings().button);
}

static void show(Ctx& ctx, bool silent, bool button) {
    ButtonState look{};
    look.flags = (silent ? MC_BUTTON_ACTIVE : 0u) | (button ? 0u : MC_BUTTON_HIDDEN);
    look.tooltip = silent ? Str("Silent typing: on") : Str("Silent typing: off");
    ctx.button<keys>(look);
}

MC_COMMAND(silent_typing, (Opt<bool> on), "Hide that you're typing", .args = {"On or off; omit to switch"}) {
    const bool next = on ? *on : !ctx.settings().silent;
    ctx.set_setting(Setting::silent, next);
    show(ctx, next, ctx.settings().button);
    return Reply::toast(next ? Str("Others won't see you typing") : Str("Others see you typing again"));
}

static bool quiet(Ctx& ctx, const TypingNotice&) {
    return ctx.settings().silent;
}
static void changed(Ctx& ctx, const SettingChanged&) {
    show(ctx, ctx.settings().silent, ctx.settings().button); // the page changed a value
}
static void start(Ctx& ctx) {
    show(ctx, ctx.settings().silent, ctx.settings().button);
}

MC_HOOKS(quiet, changed);
MC_PLUGIN(.owner = 0x6D63'736C'7479'7065, .name = "Silent Typing", .version = "1.0.0",
          .summary = "Doesn't tell others when you're typing.", .api_level = 1, .start = start);
