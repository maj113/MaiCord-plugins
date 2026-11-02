Shows what you are listening to as your activity ("Listening to ...") by asking Last.fm for your latest scrobble every few seconds. When nothing is playing, the activity is cleared. Any player that scrobbles to Last.fm works.

You need a Last.fm account and a free API key from `last.fm/api/account/create`. The key is stored encrypted on your computer and is sent only to Last.fm.

### Settings

- **Last.fm username** and **Last.fm API key**: both are required.
- **Activity name**: Last.fm (the default), the song, the artist or the album.
- **Add the album to the activity**: on by default.
- **Check every (seconds)**: 20 by default, from 10 to 120.

### Network

Connects to `ws.audioscrobbler.com` only, over HTTPS, to read your recent tracks. It can set your activity and nothing else.

Inspired by Vencord's MusicRichPresence plugin. Written from scratch for MaiCord; no Vencord code.
