// Blur NSFW: blurs, or hides, the images and videos of messages in age-restricted channels.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Choice, action, "Media in age-restricted channels", 0, .items = {"Blur", "Hide"}),
            (Toggle, dms, "Also in DMs and group chats", false),
            (Toggle, own, "Also on your own messages", false));

static void decorate(Ctx& ctx, const Message& m, Decoration& d) {
    const Settings& s = ctx.settings();
    if (!m.has(MC_MESSAGE_NSFW) && !(s.dms && m.has(MC_MESSAGE_PRIVATE)))
        return;
    if (m.own() && !s.own)
        return;
    if (s.action == 1)
        d.hide_media();
    else
        d.blur_media();
}

static void changed(Ctx& ctx, const SettingChanged&) {
    ctx.invalidate_message(0); // every message is decorated again
}

MC_HOOKS(mc::filter<decorate, MC_FILTER_HAS_MEDIA>, changed);
MC_PLUGIN(.owner = 0x6D63'626C'726E'7366, .name = "Blur NSFW", .version = "1.0.0",
          .summary = "Blurs the images and videos of age-restricted channels.");
