Stops MaiCord from sending the "is typing…" notice, so nobody in the channel sees that you're writing. Your messages are sent as usual.

A keyboard button in the chat bar and the `/silent_typing` command switch it; `/silent_typing on:false` turns it off, with no argument it switches.

### Settings

- **Don't send typing notices**: on by default.
- **Show a button in the chat bar**: on by default.

It makes no requests and reads nothing: it only tells MaiCord to skip the notice.

Inspired by Vencord's SilentTyping plugin. Written from scratch for MaiCord; no Vencord code.
