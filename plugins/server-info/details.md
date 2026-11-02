Adds **Server info** to a server's context menu: a dialog with its name, when it was created and how long ago, its owner, member and online counts, channel, role and emoji counts, verification level, boosts, how many permissions you hold there and whether it's muted or has unread mentions. **Copy ID** copies the server's ID.

### Settings

- **Show IDs**: on by default; shows the server's ID and its owner's.

Figures MaiCord doesn't have yet are left out rather than shown as zero. The creation date comes from the server's ID and is shown in your local time. It only reads what MaiCord already holds and makes no network requests; it needs the clipboard permission for Copy ID.

Inspired by Vencord's ServerInfo plugin. Written from scratch for MaiCord; no Vencord code.
