// Preview Message: a chat-bar button that shows what you've typed as a message
// only you can see, so you can check the formatting before you send it. The
// host shows it as an ephemeral message, whose footer says only you can see it.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, replace, "Replace the previous preview", true));

struct State {
    u64 channel, message; // the preview on screen, 0 when none
};
MC_STATE(State, .version = 1);

MC_BUTTON(preview, surface::chat_bar, "Preview message", "lucide/eye") {
    Text<MC_ACTION_TEXT_MAX> text;
    if (!ctx.composer.text(text)) {
        ctx.toast("Couldn't read what you typed", Tone::warning);
        return;
    }
    if (text.view().trimmed().empty()) {
        ctx.toast("Type a message to preview first", Tone::warning);
        return;
    }
    State& shown = ctx.state<State>();
    if (ctx.settings().replace && shown.message)
        ctx.remove_local_message(shown.channel, shown.message);
    shown = {};
    const u64 id = ctx.local_message(text, button.channel());
    if (!id) {
        ctx.toast("Couldn't show the preview", Tone::warning);
        return;
    }
    shown = {button.channel(), id};
}

MC_PLUGIN(.owner = 0x6D63'7072'6576'6D67, .name = "Preview Message", .version = "1.0.1",
          .summary = "Shows what you've typed as a message only you see.", .permissions = MC_PERM_COMPOSER,
          .api_level = 1);
