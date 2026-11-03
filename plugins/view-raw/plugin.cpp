// View Raw: a button on a message that shows its text exactly as it was sent (markdown and all), or what MaiCord
// knows about the message as JSON, and copies either.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((Choice, view, "Show", 0, .items = {"Message text", "Message details (JSON)"}));

constexpr u32 kShown = 2000;  // what the dialog shows
constexpr u32 kCopied = 4000; // what a copy can carry
using Copy = Text<kCopied>;

// What Copy puts on the clipboard: the whole text, of which the dialog may show only the start.
struct State {
    u32 bytes;
    char text[kCopied];
};
MC_STATE(State, .version = 1);

// -- Writing JSON ------------------------------------------------------------------

static void number(Copy& out, u64 value) {
    char buffer[20];
    u32 count = 0;
    do {
        buffer[count++] = static_cast<char>('0' + value % 10);
        value /= 10;
    } while (value);
    while (count)
        out.push(buffer[--count]);
}
static void padded(Copy& out, u64 value, u32 width) {
    char buffer[4];
    for (u32 i = width; i--; value /= 10)
        buffer[i] = static_cast<char>('0' + value % 10);
    out.append(Str(buffer, width));
}
// "YYYY-MM-DDTHH:MM:SS.mmmZ" for Unix milliseconds (proleptic Gregorian calendar).
static void iso(Copy& out, u64 ms) {
    const i64 days = static_cast<i64>(ms / 86'400'000) + 719'468;
    const i64 era = days / 146'097;
    const i64 doe = days - era * 146'097;
    const i64 yoe = (doe - doe / 1'460 + doe / 36'524 - doe / 146'096) / 365;
    const i64 doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    const i64 mp = (5 * doy + 2) / 153;
    const i64 month = mp < 10 ? mp + 3 : mp - 9;
    const u64 in_day = ms % 86'400'000;
    padded(out, static_cast<u64>(yoe + era * 400 + (month <= 2 ? 1 : 0)), 4);
    out.push('-');
    padded(out, static_cast<u64>(month), 2);
    out.push('-');
    padded(out, static_cast<u64>(doy - (153 * mp + 2) / 5 + 1), 2);
    out.push('T');
    padded(out, in_day / 3'600'000, 2);
    out.push(':');
    padded(out, in_day / 60'000 % 60, 2);
    out.push(':');
    padded(out, in_day / 1'000 % 60, 2);
    out.push('.');
    padded(out, in_day % 1'000, 3);
    out.push('Z');
}
// Appends text as the inside of a JSON string, keeping `reserve` bytes free. Stops before the first character
// that doesn't fit (a UTF-8 character goes in whole or not at all) and says whether everything went in.
static bool escape(Copy& out, Str text, u32 reserve) {
    constexpr char kHex[] = "0123456789abcdef";
    for (u32 at = 0; at < text.bytes;) {
        const u8 byte = static_cast<u8>(text[at]);
        char chunk[6];
        u32 length = 1;
        if (byte >= 0xC0 && byte < 0xE0)
            length = 2;
        else if (byte >= 0xE0 && byte < 0xF0)
            length = 3;
        else if (byte >= 0xF0)
            length = 4;
        if (byte == '"' || byte == '\\' || byte == '\n' || byte == '\r' || byte == '\t') {
            chunk[0] = '\\';
            chunk[1] = byte == '\n' ? 'n' : byte == '\r' ? 'r' : byte == '\t' ? 't' : static_cast<char>(byte);
            length = 2;
        } else if (byte < 0x20) {
            chunk[0] = '\\', chunk[1] = 'u', chunk[2] = '0', chunk[3] = '0';
            chunk[4] = kHex[byte >> 4];
            chunk[5] = kHex[byte & 15];
            length = 6;
        }
        const bool plain = byte >= 0x20 && byte != '"' && byte != '\\';
        const Str piece = plain ? text.sub(at, length) : Str(chunk, length);
        if (out.size() + piece.bytes + reserve > kCopied || !out.append(piece))
            return false;
        at += plain ? length : 1;
    }
    return true;
}
static void field(Copy& out, Str name, u64 id) { // "name": "<id>", the way Discord writes ids
    out.append("  \"");
    out.append(name);
    out.append("\": \"");
    number(out, id);
    out.append("\",\n");
}

// What MaiCord holds about the message; the content goes last, cut where the copy runs out.
static void details(Ctx& ctx, const Message& message, Copy& out) {
    out.append("{\n");
    field(out, "id", message.id());
    field(out, "channel_id", message.channel());
    if (message.guild())
        field(out, "guild_id", message.guild());
    out.append("  \"author\": {\"id\": \"");
    number(out, message.author());
    out.push('"');
    if (const auto user = ctx.read.user(message.author(), message.guild())) {
        out.append(", \"username\": \"");
        escape(out, user->username(), 64);
        out.push('"');
    }
    out.append("},\n  \"timestamp\": \"");
    iso(out, message.timestamp_ms);
    out.append("\",\n  \"edited_timestamp\": ");
    if (message.edited_ms) {
        out.push('"');
        iso(out, message.edited_ms);
        out.push('"');
    } else {
        out.append("null");
    }
    out.append(",\n  \"type\": ");
    number(out, message.type);
    out.append(",\n");
    if (message.reply_to)
        field(out, "reply_to", message.reply_to);
    out.append("  \"attachments\": ");
    number(out, message.attachment_count);
    out.append(",\n  \"embeds\": ");
    number(out, message.embed_count);
    out.append(",\n  \"own\": ");
    out.append(message.own() ? Str("true") : Str("false"));
    out.append(",\n  \"bot\": ");
    out.append(message.bot() ? Str("true") : Str("false"));
    out.append(",\n  \"pinned\": ");
    out.append(message.has(MC_MESSAGE_PINNED) ? Str("true") : Str("false"));
    out.append(",\n  \"content\": \"");
    escape(out, message.content(), 3);
    out.append("\"\n}");
}

// -- The button ---------------------------------------------------------------------

static void copied(Ctx& ctx, const ModalResult& result, u64) {
    if (!result.accepted())
        return;
    const State& state = ctx.state<State>();
    if (ctx.copy(Str(state.text, state.bytes)) != MC_OK)
        ctx.toast("Couldn't copy", Tone::warning);
}

MC_BUTTON(view_raw, surface::message_popover, "View raw", "lucide/code") {
    const Message& message = button.message();
    const bool json = ctx.settings().view == 1;
    Copy copy;
    if (json)
        details(ctx, message, copy);
    else
        copy.append(message.content());
    if (copy.empty()) {
        ctx.toast("This message has no text");
        return;
    }
    State& state = ctx.state<State>();
    state.bytes = copy.size();
    for (u32 i = 0; i < state.bytes; ++i)
        state.text[i] = copy.data()[i];

    u32 shown = copy.size() < kShown ? copy.size() : kShown;
    while (shown < copy.size() && (static_cast<u8>(copy.data()[shown]) & 0xC0) == 0x80)
        --shown; // cut on a character boundary
    Modal modal{};
    modal.flags = MC_MODAL_READ_ONLY; // shown, not edited: Copy takes the text
    modal.has_input = 1;
    modal.title = json ? Str("Message details") : Str("Raw message");
    if (shown < copy.size())
        modal.body = Str("Too long to show whole. Copy takes all of it.");
    modal.accept = Str("Copy");
    modal.cancel = Str("Close");
    modal.input_label = json ? Str("JSON") : Str("Text");
    modal.input_initial = Str(copy.data(), shown);
    if (ctx.modal<copied>(modal) != MC_OK)
        ctx.toast("Couldn't open the viewer", Tone::warning);
}

MC_PLUGIN(.owner = 0x6D63'7669'6577'7277, .name = "View Raw", .version = "1.1.0",
          .summary = "Shows a message's raw text or details and copies them.", .permissions = MC_PERM_CLIPBOARD, .api_level = 3);
