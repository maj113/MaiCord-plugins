// Custom RPC: sets an activity of your own ("Playing ...", "Watching ...") from
// the text you type in its settings, optionally with an elapsed timer.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, enabled, "Show this activity", false),
            (Choice, kind, "Type", 0, .items = {"Playing", "Listening to", "Watching", "Competing in"}),
            (Text, name, "Name", {}, .hint = "What you are doing", .max_bytes = 128),
            (Text, details, "Details", {}, .hint = "First line under the name", .max_bytes = 128),
            (Text, state, "State", {}, .hint = "Second line", .max_bytes = 128),
            (Choice, timestamp, "Timer", 0, .items = {"None", "Elapsed since you turned it on"}),
            (Text, app_id, "Application ID (optional)", {}, .description = "A Discord application id to attach", .max_bytes = 20));

struct State {
    u64 since;  // when the activity was turned on (Unix ms)
    u32 active; // an activity is set
    u32 reserved;
};
MC_STATE(State, .version = 1);

constexpr u64 kApply = 1;
constexpr u32 kActivityTypes[] = {MC_ACTIVITY_PLAYING, MC_ACTIVITY_LISTENING, MC_ACTIVITY_WATCHING,
                                  MC_ACTIVITY_COMPETING};

static u64 digits(Str text) {
    u64 value = 0;
    for (char c : text) {
        if (c < '0' || c > '9' || value > (0xFFFFFFFFFFFFFFFFull - 9) / 10)
            return 0;
        value = value * 10 + static_cast<u64>(c - '0');
    }
    return value;
}

static void apply(Ctx& ctx) {
    const Settings& s = ctx.settings();
    State& state = ctx.state<State>();
    if (!s.enabled || s.name.trimmed().empty()) {
        if (state.active)
            ctx.set_activity(nullptr);
        state.active = 0;
        return;
    }
    const u64 since = state.active ? state.since : ctx.now_ms();
    Activity activity{};
    activity.type = kActivityTypes[s.kind];
    activity.name = s.name.trimmed();
    activity.details = s.details.trimmed();
    activity.state = s.state.trimmed();
    activity.application_id = digits(s.app_id.trimmed());
    activity.start_ms = s.timestamp == 1 ? since : 0;
    const mc_status status = ctx.set_activity(&activity);
    if (status == MC_OK) {
        state.active = 1;
        state.since = since;
    } else if (status == MC_E_RATE_LIMITED || status == MC_E_BUSY) {
        ctx.timer(kApply, 5000); // two updates per ten seconds are allowed
    }
}

static void on_timer(Ctx& ctx, const Timer&) {
    apply(ctx);
}
static void on_setting(Ctx& ctx, const SettingChanged&) {
    ctx.timer(kApply, 1500); // once the user has stopped typing
}

static void start(Ctx& ctx) {
    apply(ctx);
}

MC_HOOKS(on_timer, on_setting);
MC_PLUGIN(.owner = 0x6D63'6375'7372'7063, .name = "Custom RPC", .version = "1.0.0",
          .summary = "Sets a custom activity from text you write.", .permissions = MC_PERM_ACT_PRESENCE,
          .start = start);
