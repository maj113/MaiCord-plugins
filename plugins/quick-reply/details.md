Pick the message you reply to from the keyboard. **Ctrl+Up** moves the reply to the previous message of the open channel, **Ctrl+Down** to the next one, and the composer keeps focus so you can type right away. Moving down from the newest message drops the reply, and Escape in the composer does too.

### Settings

- **Reply to the previous message** and **Reply to the next message**: Ctrl+Up and Ctrl+Down by default; rebind them on the plugin's settings page.
- **Ping the author**: on by default.
- **Skip your own messages**: on by default.
- **Skip bots**: off by default.

It walks the messages MaiCord has loaded for the channel (the history you've scrolled through), never fetches more, and skips system messages and deleted ones. It does nothing while you are editing a message.

Inspired by Vencord's QuickReply plugin. Written from scratch for MaiCord; no Vencord code.
