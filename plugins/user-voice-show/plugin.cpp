// User Voice Show: marks users who are in a voice channel, with the channel's name; click it on a profile to open it.
// Inspired by Vencord's UserVoiceShow.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, members, "Member list", true),
            (Toggle, authors, "Next to message authors", false),
            (Toggle, profiles, "On profiles", true));

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
    const Settings& s = ctx.settings();
    const bool profile = user.where == MC_USER_PROFILE;
    if (!(profile ? s.profiles : user.where == MC_USER_MEMBER_ROW ? s.members : s.authors))
        return;
    const u64 voice = ctx.read.voice_channel(user.id(), user.guild());
    if (!voice)
        return;
    const auto channel = ctx.read.channel(voice);
    const Str name = channel && !channel->name().empty() ? channel->name() : Str("a voice channel");
    Text<MC_NODE_TOOLTIP_MAX> tip;
    tip.append("In voice: ");
    fit(tip, name);
    if (const auto guild = ctx.read.guild(channel ? channel->guild() : 0); guild && !guild->name().empty() &&
        tip.size() + 3 + guild->name().size() <= tip.capacity()) {
        tip.append(", ");
        tip.append(guild->name());
    }
    if (profile) { // a chip that opens the channel
        Text<MC_NODE_SHORT_MAX> label;
        label.append("In ");
        fit(label, name);
        Node chip = button(label, voice, Tone::accent);
        chip.icon = Str("lucide/volume-2");
        chip.tooltip = tip;
        d.accessory(chip);
    } else {
        Text<MC_NODE_SHORT_MAX> label;
        fit(label, name);
        d.badge(badge(label, Tone::accent, "lucide/volume-2", tip));
    }
}

// A join or leave: ask again about that user everywhere.
static void voiced(Ctx& ctx, const ev::VoiceState& e) {
    ctx.invalidate_user(e.user_id);
}

static void opened(Ctx& ctx, const NodeAction& action) {
    if (action.tag)
        ctx.open_channel(action.tag);
}

static void changed(Ctx& ctx, const SettingChanged&) {
    ctx.invalidate_user(0);
}

MC_HOOKS(decorate, voiced, opened, changed);
MC_PLUGIN(.owner = 0x6D63'766F'6963'6575, .name = "User Voice Show", .version = "1.0.1",
          .summary = "Shows which voice channel a user is in.", .permissions = MC_PERM_READ_ACTIVITY);
