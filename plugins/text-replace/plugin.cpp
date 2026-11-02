// Text Replace: rewrites the messages you send with a list of rules. A rule is
// "find => replace"; a find between slashes, /pattern/ or /pattern/i, is a
// regular expression (groups, | alternation, [classes], \d \w \s \b, * + ? {n,m}
// and lazy forms) and its replacement may use $1..$9, $& and $$.
#include <maicord/sdk/plugin.hpp>
using namespace mc;

MC_SETTINGS((TextList, rules, "Rules", {}, .description = "Applied in order to what you send.",
             .hint = "find => replace, or /pattern/ => $1", .max_bytes = 256),
            (Toggle, nocase, "Ignore case", false), (Toggle, on_edit, "Also change edited messages", true));

// ---- A small backtracking regular-expression engine (bytes, UTF-8 aware) -------

namespace re {
using i16 = int16_t;
enum : u8 { kChar, kAny, kSet, kSplit, kJump, kSave, kBol, kEol, kWord, kNotWord, kMatch };
struct Inst {
    u8 op, arg; // kChar: the byte; kSet: the set; kSave: the capture slot
    i16 x, y;   // kSplit: try pc+x, then pc+y; kJump: pc+x
};
constexpr u32 kCodeMax = 192, kSetMax = 8, kStackMax = 4600, kStepsMax = 200'000, kRepeatMax = 32;
constexpr u32 kInfinite = ~0u;

struct Prog {
    Inst code[kCodeMax];
    u64 sets[kSetMax][4];
    u32 size, set_count;
    bool fold, failed;
};

constexpr bool word(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
}
constexpr void add(u64 (&set)[4], u32 lo, u32 hi) {
    for (u32 b = lo; b <= hi; ++b)
        set[b >> 6] |= 1ull << (b & 63);
}
// \d \w \s and their negations, into set; false for any other letter.
constexpr bool add_class(u64 (&set)[4], char e) {
    u64 part[4] = {};
    switch (e | 0x20) {
    case 'd': add(part, '0', '9'); break;
    case 'w': add(part, '0', '9'); add(part, 'A', 'Z'); add(part, 'a', 'z'); add(part, '_', '_'); break;
    case 's': add(part, '\t', '\r'); add(part, ' ', ' '); break;
    default: return false;
    }
    for (u32 i = 0; i < 4; ++i)
        set[i] |= e < 'a' ? ~part[i] : part[i]; // an upper-case letter negates
    return true;
}

struct Compiler {
    Prog& p;
    Str s;
    u32 at = 0, groups = 1, depth = 0;

    void fail() {
        p.failed = true;
    }
    void emit(u8 op, u8 arg = 0, i32 x = 0, i32 y = 0) {
        if (p.size >= kCodeMax)
            return fail();
        p.code[p.size++] = {op, arg, static_cast<i16>(x), static_cast<i16>(y)};
    }
    void insert(u32 index, Inst inst) {
        if (p.size >= kCodeMax)
            return fail();
        for (u32 i = p.size++; i > index; --i)
            p.code[i] = p.code[i - 1];
        p.code[index] = inst;
    }
    void copy(u32 from, u32 length) {
        if (p.size + length > kCodeMax)
            return fail();
        for (u32 i = 0; i < length; ++i)
            p.code[p.size + i] = p.code[from + i];
        p.size += length;
    }
    void patch(u32 split, u32 target, bool lazy) { // the split's other way goes to target
        p.code[split].y = static_cast<i16>(target - split);
        if (lazy) {
            const i16 x = p.code[split].x;
            p.code[split].x = p.code[split].y;
            p.code[split].y = x;
        }
    }
    void literal(char c) {
        emit(kChar, static_cast<u8>(p.fold ? Str::lower(c) : c));
    }
    bool more() const {
        return at < s.size() && !p.failed;
    }

    // One character of a [class] or a literal escape: its byte, or ~0 after a failure.
    u32 member(char c, bool in_class, u64 (&set)[4]) {
        if (c != '\\') {
            if (static_cast<u8>(c) >= 0x80)
                fail(); // classes are ASCII only
            return static_cast<u8>(c);
        }
        if (at >= s.size())
            return fail(), ~0u;
        const char e = s[at++];
        if (in_class && add_class(set, e))
            return ~0u - 1; // a whole class: no range follows
        switch (e) {
        case 'n': return '\n';
        case 't': return '\t';
        case 'r': return '\r';
        case 'f': return '\f';
        case 'v': return '\v';
        default:
            if (word(e) || static_cast<u8>(e) >= 0x80)
                fail(); // \1, \x.. and other letters are not supported
            return static_cast<u8>(e);
        }
    }
    void set_class() {
        const bool negate = more() && s[at] == '^';
        at += negate;
        u64 set[4] = {};
        for (;;) {
            if (!more())
                return fail();
            const char c = s[at++];
            if (c == ']')
                break;
            const u32 lo = member(c, true, set);
            if (lo == ~0u - 1 || p.failed)
                continue;
            u32 hi = lo;
            if (at + 1 < s.size() && s[at] == '-' && s[at + 1] != ']') {
                ++at;
                hi = member(s[at++], true, set);
                if (hi >= 0x80 || hi < lo)
                    return fail();
            }
            add(set, lo, hi);
        }
        if (p.fold)
            for (u32 c = 'a'; c <= 'z'; ++c)
                if ((set[c >> 6] >> (c & 63) & 1) || (set[(c - 32) >> 6] >> ((c - 32) & 63) & 1))
                    add(set, c, c), add(set, c - 32, c - 32);
        if (negate)
            for (u64& bits : set)
                bits = ~bits;
        add_set(set);
    }
    void add_set(const u64 (&set)[4]) {
        if (p.set_count >= kSetMax)
            return fail();
        for (u32 i = 0; i < 4; ++i)
            p.sets[p.set_count][i] = set[i];
        emit(kSet, static_cast<u8>(p.set_count++));
    }

    void group() {
        bool capture = true;
        if (at + 1 < s.size() && s[at] == '?' && s[at + 1] == ':') {
            capture = false;
            at += 2;
        }
        u32 slot = 0;
        if (capture) {
            if (groups >= 10)
                return fail();
            slot = 2 * groups++;
            emit(kSave, static_cast<u8>(slot));
        }
        if (++depth > 6)
            return fail();
        alternatives();
        --depth;
        if (!more() || s[at] != ')')
            return fail();
        ++at;
        if (capture)
            emit(kSave, static_cast<u8>(slot + 1));
    }
    void atom() {
        const char c = s[at++];
        switch (c) {
        case '(': return group();
        case '[': return set_class();
        case '.': return emit(kAny);
        case '^': return emit(kBol);
        case '$': return emit(kEol);
        case '*': case '+': case '?': return fail(); // nothing to repeat
        case '\\': {
            if (at >= s.size())
                return fail();
            const char e = s[at];
            u64 set[4] = {};
            if (e == 'b' || e == 'B')
                return ++at, emit(e == 'b' ? kWord : kNotWord);
            if (add_class(set, e))
                return ++at, add_set(set);
            const u32 byte = member(c, false, set);
            if (!p.failed)
                literal(static_cast<char>(byte));
            return;
        }
        default:
            literal(c);
            while (at < s.size() && static_cast<u8>(c) >= 0xC0 && (static_cast<u8>(s[at]) & 0xC0) == 0x80)
                literal(s[at++]); // the rest of a UTF-8 character stays in one atom
        }
    }

    // {n}, {n,} or {n,m} at s[at], consumed only when it is one.
    bool counts(u32& min, u32& max) {
        u32 i = at + 1, value[2] = {0, 0};
        bool comma = false, digits[2] = {false, false};
        for (; i < s.size() && s[i] != '}'; ++i) {
            if (s[i] == ',' && !comma)
                comma = true;
            else if (s[i] >= '0' && s[i] <= '9' && value[comma] < 1000)
                value[comma] = value[comma] * 10 + static_cast<u32>(s[i] - '0'), digits[comma] = true;
            else
                return false;
        }
        if (i >= s.size() || !digits[0] || (comma && digits[1] && value[1] < value[0]))
            return false;
        min = value[0];
        max = comma ? (digits[1] ? value[1] : kInfinite) : min;
        at = i + 1;
        return true;
    }
    void star(u32 start, bool lazy) {
        insert(start, {kSplit, 0, 1, 0});
        const u32 jump = p.size;
        emit(kJump, 0, static_cast<i32>(start) - static_cast<i32>(jump));
        patch(start, p.size, lazy);
    }
    void plus(u32 start, bool lazy) {
        const u32 split = p.size;
        emit(kSplit, 0, static_cast<i32>(start) - static_cast<i32>(split), 1);
        if (lazy) { // leave first, loop only when that fails
            p.code[split].x = 1;
            p.code[split].y = static_cast<i16>(start - split);
        }
    }
    // The atom in code[start, size) repeated min to max times.
    void repeat(u32 start, u32 min, u32 max, bool lazy) {
        if (max == 0)
            return void(p.size = start);
        if ((max > kRepeatMax && max != kInfinite) || min > kRepeatMax)
            return fail();
        const u32 length = p.size - start;
        if (max == kInfinite) {
            if (min == 0)
                return star(start, lazy);
            for (u32 i = 2; i < min; ++i)
                copy(start, length);
            u32 last = start;
            if (min > 1)
                last = p.size, copy(start, length);
            return plus(last, lazy);
        }
        u32 splits[kRepeatMax], count = 0, source = start;
        if (min == 0) { // the atom itself is the first optional copy
            insert(start, {kSplit, 0, 1, 0});
            splits[count++] = start;
            source = start + 1;
        }
        for (u32 i = 1; i < min; ++i)
            copy(source, length);
        for (u32 i = min == 0 ? 1 : min; i < max; ++i) {
            splits[count++] = p.size;
            emit(kSplit, 0, 1, 0);
            copy(source, length);
        }
        for (u32 i = 0; i < count; ++i)
            patch(splits[i], p.size, lazy);
    }
    void quantified() {
        const u32 start = p.size;
        atom();
        if (!more())
            return;
        u32 min = 1, max = 1;
        switch (s[at]) {
        case '*': min = 0, max = kInfinite, ++at; break;
        case '+': max = kInfinite, ++at; break;
        case '?': min = 0, ++at; break;
        case '{':
            if (!counts(min, max))
                return;
            break;
        default: return;
        }
        const bool lazy = at < s.size() && s[at] == '?';
        at += lazy;
        repeat(start, min, max, lazy);
    }
    void sequence() {
        while (more() && s[at] != '|' && s[at] != ')')
            quantified();
    }
    void alternatives() {
        u32 branch = p.size, jumps[8], count = 0;
        sequence();
        while (more() && s[at] == '|') {
            if (count == 8)
                return fail();
            insert(branch, {kSplit, 0, 1, 0});
            jumps[count++] = p.size;
            emit(kJump);
            patch(branch, p.size, false);
            ++at;
            branch = p.size;
            sequence();
        }
        for (u32 i = 0; i < count; ++i)
            p.code[jumps[i]].x = static_cast<i16>(p.size - jumps[i]);
    }
};

inline bool compile(Str pattern, bool fold, Prog& p) {
    p.size = p.set_count = 0;
    p.fold = fold;
    p.failed = false;
    Compiler c{p, pattern};
    c.alternatives();
    if (c.at != pattern.size()) // an unmatched ')'
        c.fail();
    c.emit(kMatch);
    return !p.failed;
}

struct Back {
    i32 pc; // negative: restore capture ~pc to sp
    u32 sp;
};

// Runs p on text from one start position; caps gets 10 (start, end) pairs, -1 when unset.
// stack is scratch for kStackMax entries.
inline bool run(const Prog& p, Str text, u32 from, i32 (&caps)[20], Back* stack, u32& steps) {
    u32 top = 0, sp = from;
    i32 pc = 0;
    for (i32& c : caps)
        c = -1;
    caps[0] = static_cast<i32>(from);
    const auto char_end = [&](u32 at) { // past the UTF-8 character that starts at at
        const u8 lead = static_cast<u8>(text[at++]);
        while (lead >= 0xC0 && at < text.size() && (static_cast<u8>(text[at]) & 0xC0) == 0x80)
            ++at;
        return at;
    };
    for (;;) {
        if (++steps > kStepsMax)
            return false;
        const Inst& in = p.code[pc];
        bool ok = true;
        switch (in.op) {
        case kChar:
            ok = sp < text.size() && (p.fold ? Str::lower(text[sp]) : text[sp]) == static_cast<char>(in.arg);
            sp += ok, pc += ok;
            break;
        case kAny:
            ok = sp < text.size() && text[sp] != '\n' && text[sp] != '\r';
            if (ok)
                sp = char_end(sp), ++pc;
            break;
        case kSet:
            ok = sp < text.size() && (p.sets[in.arg][static_cast<u8>(text[sp]) >> 6] >> (static_cast<u8>(text[sp]) & 63) & 1);
            if (ok)
                sp = char_end(sp), ++pc;
            break;
        case kSplit:
            if (top == kStackMax)
                return false;
            stack[top++] = {pc + in.y, sp};
            pc += in.x;
            break;
        case kJump: pc += in.x; break;
        case kSave:
            if (top == kStackMax)
                return false;
            stack[top++] = {~static_cast<i32>(in.arg), static_cast<u32>(caps[in.arg])};
            caps[in.arg] = static_cast<i32>(sp);
            ++pc;
            break;
        case kBol: ok = sp == 0, pc += ok; break;
        case kEol: ok = sp == text.size(), pc += ok; break;
        case kWord:
        case kNotWord: {
            const bool edge = (sp > 0 && word(text[sp - 1])) != (sp < text.size() && word(text[sp]));
            ok = edge == (in.op == kWord);
            pc += ok;
            break;
        }
        default: // kMatch
            caps[1] = static_cast<i32>(sp);
            return true;
        }
        while (!ok) { // backtrack
            if (!top)
                return false;
            const Back back = stack[--top];
            if (back.pc < 0) {
                caps[~back.pc] = static_cast<i32>(back.sp);
                continue;
            }
            pc = back.pc, sp = back.sp, ok = true;
        }
    }
}
} // namespace re

// ---- Rules ---------------------------------------------------------------------

struct Rule {
    Str find, with;
    bool pattern, fold;
    re::Prog prog;
};
// What one call shares between its rules: the backtrack stack and the steps taken.
struct Work {
    re::Back stack[re::kStackMax];
    u32 steps;
};

// "find => replace" (the arrow has a space before it, and a space or the end after it).
// A find between slashes, /pattern/ or /pattern/i, is a pattern. False when the line isn't a usable rule.
static bool parse(Str line, bool fold, Rule& rule) {
    u32 arrow = 0;
    while (arrow + 3 <= line.size() &&
           !(line.sub(arrow, 3) == Str(" =>") && (arrow + 3 == line.size() || line[arrow + 3] == ' ')))
        ++arrow;
    const Str find = line.sub(0, arrow).trimmed();
    if (arrow + 3 > line.size() || find.empty())
        return false;
    rule.find = find;
    rule.with = line.sub(arrow + 3 + (arrow + 3 < line.size()));
    rule.fold = fold;
    rule.pattern = false;
    u32 end = find.size();
    const bool flag = end >= 4 && find[end - 1] == 'i' && find[end - 2] == '/';
    end -= flag;
    if (find[0] != '/' || end < 3 || find[end - 1] != '/')
        return true;
    rule.pattern = true;
    rule.fold = fold || flag;
    rule.find = find.sub(1, end - 2);
    return re::compile(rule.find, rule.fold, rule.prog);
}

static u32 next_char(Str text, u32 at) {
    ++at;
    while (at < text.size() && (static_cast<u8>(text[at]) & 0xC0) == 0x80)
        ++at;
    return at;
}

// The next match at or after from: caps[0..1] is where; for patterns caps has the groups too.
static bool find_next(const Rule& rule, Str text, u32 from, i32 (&caps)[20], Work& work) {
    for (u32 at = from; at <= text.size() && work.steps <= re::kStepsMax; at = next_char(text, at)) {
        if (rule.pattern) {
            if (re::run(rule.prog, text, at, caps, work.stack, work.steps))
                return true;
            continue;
        }
        ++work.steps;
        if (at + rule.find.size() > text.size())
            return false;
        const Str window = text.sub(at, rule.find.size());
        if (rule.fold ? window.equals_ascii_nocase(rule.find) : window == rule.find) {
            caps[0] = static_cast<i32>(at);
            caps[1] = static_cast<i32>(at + rule.find.size());
            return true;
        }
    }
    return false;
}

template <u32 N> static void expand(const Rule& rule, Str text, const i32 (&caps)[20], Text<N>& out) {
    if (!rule.pattern)
        return void(out.append(rule.with));
    for (u32 i = 0; i < rule.with.size(); ++i) {
        const char c = rule.with[i];
        const char d = i + 1 < rule.with.size() ? rule.with[i + 1] : '\0';
        u32 group = ~0u;
        if (c != '$')
            out.push(c);
        else if (d == '$')
            out.push('$'), ++i;
        else if (d == '&')
            group = 0, ++i;
        else if (d >= '1' && d <= '9')
            group = static_cast<u32>(d - '0'), ++i;
        else
            out.push('$');
        if (group != ~0u && caps[2 * group] >= 0 && caps[2 * group + 1] >= 0)
            out.append(text.sub(static_cast<u32>(caps[2 * group]),
                                static_cast<u32>(caps[2 * group + 1] - caps[2 * group])));
    }
}

// Writes the text with every match replaced into out; false when nothing matched or the result didn't fit.
template <u32 N> static bool replace_all(const Rule& rule, Str text, Text<N>& out, Work& work) {
    out.clear();
    i32 caps[20];
    u32 copied = 0, at = 0;
    bool any = false;
    while (at <= text.size() && find_next(rule, text, at, caps, work)) {
        const u32 from = static_cast<u32>(caps[0]), to = static_cast<u32>(caps[1]);
        out.append(text.sub(copied, from - copied));
        expand(rule, text, caps, out);
        copied = to;
        at = to > from ? to : next_char(text, to); // an empty match steps over one character
        any = true;
    }
    out.append(text.sub(copied));
    return any && !out.overflowed();
}

static void rewrite(Ctx& ctx, Draft& draft) {
    Text<MC_DRAFT_TEXT_MAX> buffer[2];
    Work work;
    work.steps = 0;
    const Str original = draft.text();
    Str text = original;
    u32 into = 0;
    for (Str line : ctx.settings().rules) {
        Rule rule;
        if (parse(line, ctx.settings().nocase, rule) && replace_all(rule, text, buffer[into], work)) {
            text = buffer[into];
            into ^= 1;
        }
    }
    if (text.data != original.data)
        draft.replace(text);
}
static void pre_send(Ctx& ctx, Draft& draft) {
    rewrite(ctx, draft);
}
static void pre_edit(Ctx& ctx, EditDraft& draft) {
    if (ctx.settings().on_edit)
        rewrite(ctx, draft);
}

// Tells the user about the first rule that can't be used.
static void changed(Ctx& ctx, const SettingChanged& change) {
    if (change.index == static_cast<u32>(Setting::on_edit))
        return;
    u32 number = 0;
    for (Str line : ctx.settings().rules) {
        ++number;
        Rule rule;
        if (line.trimmed().empty() || parse(line, ctx.settings().nocase, rule))
            continue;
        Text<80> note;
        note.append("Rule ");
        if (number >= 10)
            note.push(static_cast<char>('0' + number / 10));
        note.push(static_cast<char>('0' + number % 10));
        note.append(" isn't valid: use find => replace, and check any /pattern/");
        ctx.toast(note, Tone::warning);
        return;
    }
}

MC_HOOKS(pre_send, pre_edit, changed);
MC_PLUGIN(.owner = 0x6D63'7478'7472'6570, .name = "Text Replace", .version = "1.0.0",
          .summary = "Rewrites what you send with your own find-and-replace rules.", .api_level = 1);
