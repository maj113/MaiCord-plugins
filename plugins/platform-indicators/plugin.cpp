// Platform Indicators: which devices a user is online on (desktop, phone, browser).
// Inspired by Vencord's PlatformIndicators.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, members, "Member list", true),
            (Toggle, authors, "Next to message authors", true),
            (Toggle, profiles, "On profiles", true),
            (Toggle, hide_desktop, "Hide when only on desktop", false),
            (Toggle, status_colours, "Colour by status", true,
             .description = "Green when online, amber when idle, red on Do Not Disturb."));

struct Platform {
    u32 bit;
    Str icon, name, tip;
};
// In the order a badge names them; the first one that applies also gives its icon.
static constexpr Platform kPlatforms[] = {
    {MC_PLATFORM_MOBILE, "lucide/smartphone", "Mobile", "mobile"},
    {MC_PLATFORM_WEB, "lucide/compass", "Web", "a browser"},
    {MC_PLATFORM_DESKTOP, "lucide/monitor", "Desktop", "desktop"},
};

static Tone status_tone(u32 presence) {
    switch (presence) {
    case MC_PRESENCE_ONLINE: return Tone::positive;
    case MC_PRESENCE_IDLE: return Tone::warning;
    case MC_PRESENCE_DND: return Tone::critical;
    default: return Tone::neutral;
    }
}

static void decorate(Ctx& ctx, const User& user, Decoration& d) {
    const Settings& s = ctx.settings();
    const bool profile = user.where == MC_USER_PROFILE;
    if (!user.platforms || !(profile ? s.profiles : user.where == MC_USER_MEMBER_ROW ? s.members : s.authors) ||
        (s.hide_desktop && user.platforms == MC_PLATFORM_DESKTOP))
        return;
    const Tone tone = s.status_colours ? status_tone(user.presence) : Tone::neutral;
    if (profile) { // one chip per device
        for (const Platform& p : kPlatforms)
            if (user.platforms & p.bit) {
                Text<MC_NODE_TOOLTIP_MAX> tip;
                tip.append("Online on ");
                tip.append(p.tip);
                d.accessory(badge(p.name, tone, p.icon, tip));
            }
        return;
    }
    // Rows and names take one badge: every device's name, the most mobile one's icon.
    Text<MC_NODE_SHORT_MAX> names;
    Text<MC_NODE_TOOLTIP_MAX> tip;
    Str icon_name;
    tip.append("Online on ");
    for (const Platform& p : kPlatforms)
        if (user.platforms & p.bit) {
            if (icon_name.empty())
                icon_name = p.icon;
            else {
                names.push('+');
                tip.append(", ");
            }
            names.append(p.name);
            tip.append(p.tip);
        }
    d.badge(badge(names, tone, icon_name, tip));
}

MC_HOOKS(decorate);
MC_PLUGIN(.owner = 0x6D63'706C'6174'696E, .name = "Platform Indicators", .version = "1.0.0",
          .summary = "Shows which devices a user is online on.", .permissions = MC_PERM_READ_ACTIVITY, .api_level = 1);
