Adds a **View raw** button to a message's hover bar. It opens the message's text exactly as it was sent, with the markdown, mentions and emoji codes intact, in a box you can scroll and select from, and **Copy** puts all of it on your clipboard.

### Settings

- **Show**: *Message text* (the default) or *Message details (JSON)*. The details view lists what MaiCord holds about the message as JSON: its IDs, author, timestamps, type, attachment and embed counts, and the content as a JSON string. It is MaiCord's view of the message, not Discord's full payload.

Long text is cut in the box when it doesn't fit, with a note; Copy still takes all of it. It only reads the message you pick, makes no network requests, and needs the clipboard permission for Copy.

Inspired by Vencord's ViewRaw plugin. Written from scratch for MaiCord; no Vencord code.
