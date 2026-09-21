# Privacy Policy

Last updated: 21 September 2026.

The bot receives a Telegram user identifier, messages and submitted photos from Telegram. Meal photos and descriptions are kept in application memory for no longer than the original 30-minute draft lifetime and are removed when the operation is cancelled or completed. They are not written to SQLite or local files.

For meal recognition, the bot sends the submitted photo and/or description to Google Gemini. During product matching, Gemini receives the recognized meal and shortened FatSecret candidate and serving cards. These cards include names, brands, product features, serving information and nutrition values but exclude FatSecret IDs, URLs, OAuth credentials and Telegram identifiers. Recognition uses the Gemini Interactions API with `store=False`; matching uses the stateless Generate Content API. These choices do not prevent processing or retention that Google performs for abuse monitoring, under project logging settings, or under its applicable terms. See the [Gemini API terms](https://ai.google.dev/gemini-api/terms), [Gemini data retention documentation](https://ai.google.dev/gemini-api/docs/zdr), and [Google Privacy Policy](https://policies.google.com/privacy).

FatSecret receives OAuth-authenticated requests for the selected product, serving, quantity, meal category and date only after the user presses the final save button. SQLite stores the user's Telegram identifier, language, FatSecret OAuth tokens, connection date, premium flag, daily usage counter, and short-lived write-operation metadata consisting of an operation UUID, state and timestamps. OAuth tokens remain until the user disconnects FatSecret. Terminal write markers older than one day are removed during subsequent write-operation maintenance; an interrupted `writing` marker may remain so an uncertain POST cannot be replayed automatically. No meal photo, user-entered meal text, full FatSecret response or Gemini response is stored in SQLite.

Telegram, Google and FatSecret process data under their own terms and policies. The bot cannot promise deletion of provider-held copies. Users should not submit confidential or sensitive information beyond what is needed to identify a meal.

The bot does not sell user data and does not use meal content for advertising. Users can disconnect FatSecret in Settings to remove the stored OAuth tokens. Removal of the remaining local account record currently requires an operator request; there is no in-bot account deletion control yet.

Relevant provider policies: [fatsecret Platform API Terms](https://platform.fatsecret.com/terms), [fatsecret Privacy Policy](https://www.fatsecret.com/Default.aspx?pa=priv), and [Telegram Privacy Policy](https://telegram.org/privacy).
