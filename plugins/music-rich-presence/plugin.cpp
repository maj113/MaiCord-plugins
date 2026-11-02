// Music Rich Presence: shows the song you are scrobbling on Last.fm as your
// activity ("Listening to ..."), and clears it when the music stops.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Text, user, "Last.fm username", {}, .max_bytes = 64),
            (Secret, api_key, "Last.fm API key", {}, .description = "A free key from last.fm/api/account/create",
             .max_bytes = 64),
            (Choice, title, "Activity name", 0, .items = {"Last.fm", "Song", "Artist", "Album"}),
            (Toggle, album, "Add the album to the activity", true),
            (Slider, interval, "Check every (seconds)", 20, .min = 10, .max = 120, .step = 5));

struct State {
    u64 shown;  // hash of the activity set now
    u32 active; // an activity is set
    u32 failed; // Last.fm refused the account; told once
};
MC_STATE(State, .version = 1);

constexpr u64 kPoll = 1;     // repeating timer
constexpr u64 kRestart = 2;  // one-shot after a setting changed
constexpr u32 kActivityMax = 128;

static Str clip(Str text, u32 max) {
    if (text.bytes <= max)
        return text;
    while (max && (text[max] & 0xC0) == 0x80) // not in the middle of a character
        --max;
    return text.sub(0, max);
}

static bool contains(Str text, Str part) {
    for (u32 at = 0; at + part.bytes <= text.bytes; ++at)
        if (text.sub(at, part.bytes) == part)
            return true;
    return false;
}
// What follows the first `part` in text; empty when it doesn't occur.
static Str after(Str text, Str part) {
    for (u32 at = 0; at + part.bytes <= text.bytes; ++at)
        if (text.sub(at, part.bytes) == part)
            return text.sub(at + part.bytes);
    return {};
}

static void clear(Ctx& ctx) {
    State& state = ctx.state<State>();
    if (state.active)
        ctx.set_activity(nullptr);
    state.active = 0;
    state.shown = 0;
}

static void show(Ctx& ctx, Str song, Str artist, Str album) {
    const Settings& s = ctx.settings();
    State& state = ctx.state<State>();
    Text<2 * kActivityMax + 8> line;
    line.append(artist);
    if (s.album && !album.empty()) {
        line.append(" \xE2\x80\xA2 "); // a bullet
        line.append(album);
    }
    Activity activity{};
    activity.type = MC_ACTIVITY_LISTENING;
    activity.name = s.title == 1 && !song.empty()     ? song
                    : s.title == 2 && !artist.empty() ? artist
                    : s.title == 3 && !album.empty()  ? album
                                                      : Str("Last.fm");
    activity.name = clip(activity.name, kActivityMax);
    activity.details = clip(song, kActivityMax);
    activity.state = clip(line, kActivityMax);

    u64 hash = 14695981039346656037ull; // FNV-1a over what the activity shows
    const mc_str parts[] = {activity.name, activity.details, activity.state};
    for (const mc_str& part : parts)
        for (u32 i = 0; i < part.bytes; ++i)
            hash = (hash ^ static_cast<u8>(part.data[i])) * 1099511628211ull;
    if (state.active && state.shown == hash)
        return;
    if (ctx.set_activity(&activity) == MC_OK) { // a rate-limited call is tried again at the next check
        state.active = 1;
        state.shown = hash;
    }
}

static void on_tracks(Ctx& ctx, const HttpResult& r, u64) {
    State& state = ctx.state<State>();
    const Str body = r.body().sub(0, 16384); // one track is about 1 KiB
    if (!r.ok()) {
        // 4xx: Last.fm refused the username or the key. Anything else is a hiccup, tried again later.
        if (r.error() == MC_HTTP_OK && r.status() < 500 && !state.failed) {
            Text<96> message;
            json::find(body, "message", message);
            Text<MC_TOAST_TEXT_MAX> text;
            text.append("Last.fm: ");
            text.append(message.empty() ? Str("check the username and API key") : message.view());
            ctx.toast(text, Tone::warning);
            state.failed = 1;
        }
        return;
    }
    state.failed = 0;
    if (!contains(body, "\"nowplaying\":\"true\"")) {
        clear(ctx);
        return;
    }
    Text<256> song, artist, album;
    json::find(body, "name", song);
    json::find(body, "#text", artist); // the first #text of a track is its artist
    json::find(after(body, "\"album\":"), "#text", album);
    if (song.empty())
        return;
    show(ctx, song, artist, album);
}

static void poll(Ctx& ctx) {
    const Settings& s = ctx.settings();
    if (s.user.empty() || s.api_key.empty()) {
        clear(ctx);
        return;
    }
    Text<MC_HTTP_URL_MAX> address;
    address.append("https://ws.audioscrobbler.com/2.0/?method=user.getrecenttracks&limit=1&format=json&user=");
    if (url::encode(s.user, address) && address.append("&api_key=") && url::encode(s.api_key, address))
        ctx.http.get<on_tracks>(address);
}

static void restart(Ctx& ctx) {
    ctx.timer(kPoll, ctx.settings().interval * 1000u, true);
    poll(ctx);
}

static void on_timer(Ctx& ctx, const Timer& timer) {
    if (timer.id == kRestart)
        restart(ctx);
    else
        poll(ctx);
}

static void on_setting(Ctx& ctx, const SettingChanged&) {
    State& state = ctx.state<State>();
    state.shown = 0; // the next check sets the activity again
    state.failed = 0;
    ctx.timer(kRestart, 1500); // once the user has stopped typing
}

static void start(Ctx& ctx) {
    restart(ctx);
}

MC_HOOKS(on_timer, on_setting);
MC_PLUGIN(.owner = 0x6D63'6C61'7374'666D, .name = "Music Rich Presence", .version = "1.0.0",
          .summary = "Shows what you are playing on Last.fm as your activity.", .permissions = MC_PERM_ACT_PRESENCE,
          .network = {"ws.audioscrobbler.com"}, .start = start);
