// Message Logger: keeps deleted messages on screen and lists the earlier
// versions of edited ones, until you close MaiCord. Nothing is written to disk.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Toggle, deletes, "Keep deleted messages", true),
            (Toggle, edits, "Keep earlier versions of edited messages", true),
            (Header, ignore, "Ignore"),
            (Toggle, bots, "Messages from bots", false),
            (Toggle, self, "Your own messages", false),
            (UserList, people, "People"),
            (TextList, places, "Channels and servers", {}, .hint = "One ID per line", .max_bytes = 24));

// Whether one of the list's lines is exactly this id.
static bool listed(const StrList& list, u64 id) {
    for (Str line : list) {
        line = line.trimmed();
        u64 value = 0;
        bool digits = !line.empty();
        for (char c : line) {
            digits = digits && c >= '0' && c <= '9';
            value = value * 10 + static_cast<u32>(c - '0');
        }
        if (digits && value == id && id)
            return true;
    }
    return false;
}
static bool ignored(Ctx& ctx, const Message& message) {
    const Settings& s = ctx.settings();
    return message.has(MC_MESSAGE_SYSTEM | MC_MESSAGE_LOCAL) || (s.bots && message.bot()) ||
           (s.self && message.own()) || s.people.contains(message.author()) || listed(s.places, message.channel()) ||
           listed(s.places, message.guild());
}

static bool deleted(Ctx& ctx, const DeletedMessage& message) {
    if (!ctx.settings().deletes || ignored(ctx, message))
        return false;
    ctx.invalidate_message(message.id()); // the badge below
    return true;
}
static bool edited(Ctx& ctx, const Message&, const Message& after) {
    if (!ctx.settings().edits || ignored(ctx, after))
        return false;
    ctx.invalidate_message(after.id()); // the card below
    return true;
}

// Appends text cut on a character boundary to what fits, and a line feed.
static void put_line(Text<MC_CARD_TEXT_MAX>& out, Str text) {
    u32 room = MC_CARD_TEXT_MAX - out.size();
    u32 bytes = text.size() < room ? text.size() : room;
    while (bytes && bytes < text.size() && (static_cast<u8>(text[bytes]) & 0xC0) == 0x80)
        --bytes;
    out.append(text.sub(0, bytes));
    out.push('\n');
}

static void decorate(Ctx& ctx, const Message& message, Decoration& deco) {
    if (message.has(MC_MESSAGE_DELETED))
        deco.badge(badge("Deleted", Tone::critical));
    const auto kept = ctx.kept.info(message.channel(), message.id());
    if (!kept || !kept->edit_count)
        return;
    Text<MC_CARD_TEXT_MAX> history;
    for (u32 version = 1; version <= kept->edit_count; ++version) {
        Text<MC_KEEP_CONTENT_MAX> old;
        if (ctx.kept.text(message.channel(), message.id(), version, old))
            put_line(history, old);
    }
    if (!history.empty())
        deco.card(card().title("Earlier versions").text(history).caption("Newest first").tone(Tone::warning));
}

MC_HOOKS(deleted, edited, decorate);
MC_PLUGIN(.owner = 0x6D63'6D73'676C'6F67, .name = "Message Logger", .version = "1.0.0",
          .summary = "Keeps deleted and edited messages visible until you close MaiCord.", .api_level = 1);
