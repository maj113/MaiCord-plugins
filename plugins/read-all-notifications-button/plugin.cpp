// Read All Notifications Button: a button above the server list that marks every server as read.
// Inspired by Vencord's ReadAllNotificationsButton.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, confirm, "Ask before marking everything read", false));

static void mark_all(Ctx& ctx) {
    switch (ctx.mark_read(MC_READ_ALL, 0)) {
    case MC_OK:
        ctx.toast("Marking every server as read", Tone::positive);
        break;
    case MC_E_BUSY:
        ctx.toast("Still marking servers as read; try again in a moment", Tone::warning);
        break;
    default:
        ctx.toast("Couldn't mark the servers as read", Tone::warning);
    }
}

static void confirmed(Ctx& ctx, const ModalResult& result, u64) {
    if (result.accepted())
        mark_all(ctx);
}

MC_BUTTON(read_all, surface::server_list_top, "Mark all servers as read", "lucide/circle-check") {
    if (!ctx.settings().confirm)
        return mark_all(ctx);
    Modal modal{};
    modal.title = Str("Mark every server as read?");
    modal.body = Str("All unread messages and mentions in your servers are cleared.");
    modal.accept = Str("Mark as read");
    ctx.modal<confirmed>(modal);
}

MC_PLUGIN(.owner = 0x6D63'7265'6164'616C, .name = "Read All Notifications Button", .version = "1.0.0",
          .summary = "A button above the server list that marks every server as read.",
          .permissions = MC_PERM_ACT_MESSAGES, .api_level = 1);
