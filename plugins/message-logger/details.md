Keeps messages that people delete on your screen, marked **Deleted**, and shows the earlier versions of edited messages in a card under them (newest first).

Everything is kept in memory for this session only: nothing is written to disk, and closing MaiCord forgets it. MaiCord holds at most 500 messages, 32 per channel, and 8 earlier versions of each message.

### Settings

- **Keep deleted messages**: on by default.
- **Keep earlier versions of edited messages**: on by default.
- **Ignore**: **Messages from bots** (off by default), **Your own messages** (off by default), a list of **People**, and a list of **Channels and servers** (one ID per line; a server's ID ignores all of its channels).

It only sees messages MaiCord has already received; a message deleted before it was loaded can't be kept. It makes no requests, and it needs permission to read your messages and keep them visible (the consent says so).

Inspired by Vencord's MessageLogger plugin. Written from scratch for MaiCord; no Vencord code.
