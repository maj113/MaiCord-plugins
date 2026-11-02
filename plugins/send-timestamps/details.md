A calendar button in the chat bar opens a small dialog: type a date and time, pick a format, and MaiCord puts a Discord timestamp in your composer (the `t:1762370000:f` code between angle brackets). Everyone who reads it sees it in their own time zone and language.

What you can type:

- `2026-11-05 18:30` or `2026-11-05 18:30:15`: a date and time in your own time zone.
- `2026-11-05`: that day at midnight.
- `18:30`: today at that time.
- A zone after the time: `Z` or `UTC` for UTC, `+02:00` or `-0500` for another zone.

If the text can't be read, the dialog asks again with what you typed.

### Settings

- **Format**: short or long time, short or long date, short or long date and time, or relative ("in 2 hours"). It's preselected in the dialog and remembers what you picked last.

It uses your computer's clock and time zone and sends nothing: the timestamp goes into your composer and you send it yourself.

Inspired by Vencord's SendTimestamps plugin. Written from scratch for MaiCord; no Vencord code.
