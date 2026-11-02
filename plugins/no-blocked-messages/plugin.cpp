// No Blocked Messages: hides, or folds into one line, the messages of users you blocked.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Choice, mode, "Messages from blocked users", 0, .items = {"Hide completely", "Fold into one line"}));

static void decorate(Ctx& ctx, const Message& m, Decoration& d) {
    if (m.relationship != MC_RELATIONSHIP_BLOCKED)
        return;
    if (ctx.settings().mode == 1)
        d.collapse();
    else
        d.hide();
}

static void changed(Ctx& ctx, const SettingChanged&) {
    ctx.invalidate_message(0); // every message is decorated again
}

MC_HOOKS(decorate, changed);
MC_PLUGIN(.owner = 0x6D63'6E6F'626C'6B64, .name = "No Blocked Messages", .version = "1.0.0",
          .summary = "Hides the messages of users you blocked.");
