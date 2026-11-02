See who can do what. Right-click a member and choose **View permissions** to list every permission they hold in the server, grouped as General, Membership, Text, Voice and Events, plus how the channel you're in adds or removes some of them. Right-click a channel and choose **View my permissions here** for the same about yourself.

### Settings

- **Show**: *Every permission* (the default) or *Moderation and management only*, which hides everyday ones such as sending messages.
- **Show how the channel changes them**: on by default.

The permissions are the ones MaiCord computes from the member's roles and the channel's overwrites, so they are as complete as what MaiCord has cached; if it hasn't loaded a member's roles yet you are told. It reads only, asks for no permissions and makes no network requests.

Inspired by Vencord's PermissionsViewer plugin. Written from scratch for MaiCord; no Vencord code.
