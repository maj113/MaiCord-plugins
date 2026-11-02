Rewrites the messages you send (and, if you like, the ones you edit) with a list of find-and-replace rules. Rules run in order, each on the result of the one before.

### Rules

One rule per line, as `find => replace`:

- `brb => be right back` replaces every `brb`.
- `/colou?r/ => hue` uses a regular expression: write the pattern between slashes, with an `i` after the last slash to ignore case.
- In a pattern's replacement, `$1` to `$9` are the groups, `$&` is the whole match and `$$` is a dollar sign. Plain rules replace with the text as written.
- Patterns understand literals, `.`, `[a-z0-9_]` and `[^…]` (ASCII), `\d \w \s` and their capital forms, `\b`, `^`, `$`, groups `(…)` and `(?:…)`, `|`, and `* + ? {n} {n,} {n,m}` with a lazy `?` after them. Backreferences and lookarounds aren't supported.
- The arrow needs a space before it: `find => replace`. An empty replacement deletes the match.

When you change the rules, MaiCord tells you about the first line it can't use.

### Settings

- **Rules**: the list above (empty by default).
- **Ignore case**: applies to every rule; off by default.
- **Also change edited messages**: on by default.

A rule that would make the message longer than Discord allows is skipped, and so are the rules after a pattern that takes too long. It changes only your own outgoing text, on your computer, and makes no requests.

Inspired by Vencord's TextReplace plugin. Written from scratch for MaiCord; no Vencord code.
