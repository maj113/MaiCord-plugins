// No Reply Mention: replies don't ping the author, except (or only) for the
// people you list.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Choice, scope, "Don't ping", 0, .items = {"Everyone except the people below", "Only the people below"}),
            (UserList, people, "People", {}));

static void pre_send(Ctx& ctx, Draft& draft) {
    if (!draft.reply())
        return;
    const bool listed = ctx.settings().people.contains(draft.reply_author());
    if (listed == (ctx.settings().scope == 1))
        draft.set_flag(MC_DRAFT_REPLY_PING, false);
}

MC_HOOKS(pre_send);
MC_PLUGIN(.owner = 0x6D63'6E6F'7265'706C, .name = "No Reply Mention", .version = "1.0.1",
          .summary = "Turns off the ping of your replies.");
