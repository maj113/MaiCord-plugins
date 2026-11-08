// Mutual Group DMs: lists the group DMs you share with someone on their profile; click one to open it.
// Inspired by Vencord's MutualGroupDMs.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

// A profile has room for 8 chips: up to 7 group DMs and a "+N more" label.
MC_SETTINGS((Slider, limit, "Group DMs to list", 5, .min = 1, .max = 7, .step = 1));

// Appends text, cut on a character boundary with an ellipsis when it doesn't fit (room for 3 bytes is assumed).
template <u32 N> static void fit(Text<N>& out, Str text) {
    if (text.size() <= N - out.size()) {
        out.append(text);
        return;
    }
    u32 room = N - out.size() - 3;
    while (room && (static_cast<u8>(text[room]) & 0xC0) == 0x80)
        --room;
    out.append(text.sub(0, room));
    out.append("\xE2\x80\xA6");
}

static void decorate(Ctx& ctx, const User& user, Decoration& d) {
    if (user.where != MC_USER_PROFILE || user.self() || user.bot())
        return;
    u64 ids[7];
    u32 total = 0;
    const u32 listed = ctx.read.shared_group_dms(user.id(), ids, &total);
    for (u32 i = 0; i < listed && i < static_cast<u32>(ctx.settings().limit); ++i) {
        const auto channel = ctx.read.channel(ids[i]);
        const Str name = channel && !channel->name().empty() ? channel->name() : Str("Group DM");
        Text<MC_NODE_SHORT_MAX> label;
        Text<MC_NODE_TOOLTIP_MAX> tip;
        fit(label, name);
        fit(tip, name);
        Node chip = button(label, ids[i]);
        chip.icon = Str("lucide/users-round");
        chip.tooltip = tip;
        d.accessory(chip);
    }
    const u32 shown = listed < static_cast<u32>(ctx.settings().limit) ? listed : static_cast<u32>(ctx.settings().limit);
    if (total > shown) {
        Text<MC_NODE_SHORT_MAX> more;
        char digits[10];
        u32 at = sizeof(digits);
        for (u32 n = total - shown; n; n /= 10)
            digits[--at] = static_cast<char>('0' + n % 10);
        more.push('+');
        more.append(Str(digits + at, sizeof(digits) - at));
        more.append(" more");
        d.accessory(label(more));
    }
}

static void opened(Ctx& ctx, const NodeAction& action) {
    if (action.tag)
        ctx.open_channel(action.tag);
}

MC_HOOKS(decorate, opened);
MC_PLUGIN(.owner = 0x6D63'6D75'7467'646D, .name = "Mutual Group DMs", .version = "1.0.1",
          .summary = "Lists the group DMs you share with someone on their profile.",
          .permissions = MC_PERM_READ_MESSAGES);
