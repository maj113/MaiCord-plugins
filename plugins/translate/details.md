Translates messages with Google's free endpoint or DeepL. A **Translate** button on a message's hover toolbar sends its text to the chosen service and shows the result in a card under the message, with a **Hide** button. `/tr text` translates text and puts it in the composer. With "Ask before sending untranslated messages" on, sending asks first.

### Settings

- **Translate to**: English, German, French, Japanese or Spanish.
- **Ask before sending untranslated messages**: off by default.
- **Service**: Google (free) or DeepL.
- **DeepL API key**: shown for DeepL only. It is sent only to DeepL; free-plan keys (ending in `:fx`) use `api-free.deepl.com`.

### Network

The text of messages you choose to translate leaves your PC for `translate.googleapis.com`, `api-free.deepl.com` or `api.deepl.com`, depending on the service you pick. Nothing is sent until you press the button, use `/tr` or confirm a send.
