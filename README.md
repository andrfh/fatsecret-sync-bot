# fatsecret-sync-bot

**English** | [Русский](README.ru.md)

`fatsecret-sync-bot` is a non-commercial Telegram bot that recognizes meals from photos or text,
matches them with FatSecret foods, and adds confirmed items to a user's food diary.

The bot is an independent project and is not affiliated with or endorsed by FatSecret, Google,
or Telegram.

Current version: **1.0.0**

## What it does

1. Connects a user's FatSecret account through OAuth 1.0.
2. Accepts a photo, a captioned photo, or a text meal description.
3. Uses Google Gemini to recognize the meal and estimate its components and weight.
4. Matches recognized items with FatSecret foods and servings.
5. Shows the selected products, portions, mass, and macros for review.
6. Writes to FatSecret only after a separate final confirmation.

The interface is available in English and Russian. Regular users can perform four recognitions per
day; premium users are not limited.

## Stack

- Python and `python-telegram-bot`
- Google Gemini API
- FatSecret Platform API with OAuth 1.0
- SQLite (`data/app.db`)
- `systemd` on a VPS
- GitHub Actions deployment from `main`

## Local setup

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
```

Activate the environment, then install the dependencies:

```bash
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and provide:

```dotenv
TELEGRAM_API_KEY=
GEMINI_API_KEY=
FATSECRET_CONSUMER_KEY=
FATSECRET_CONSUMER_SECRET=
```

Start the bot with:

```bash
python app.py
```

The SQLite directory and schema are created automatically. The bot uses Telegram long polling.

## Tests

The local suite uses synthetic data and mocks; it does not call Telegram, Gemini, or FatSecret.

```bash
python -m unittest discover -s tests
```

## Data and safety

Meal photos, descriptions, Gemini responses, and full FatSecret responses are not stored
permanently. SQLite stores account settings, FatSecret OAuth credentials, daily usage counters,
and short write-operation markers. Meal drafts expire after 30 minutes.

Diary writes are protected against duplicate clicks. FatSecret POST requests are not retried
automatically; an uncertain response blocks replay and asks the user to check the diary.

Recognition and nutrition estimates may be inaccurate and are not medical advice.

## Documentation

- [Privacy Policy](PRIVACY.md)
- [Terms of Use](TERMS.md)
- [VPS deployment](docs/VPS_DEPLOYMENT.md)
- [Matching evaluation](docs/MATCHING_EVALUATION.md)
- [Changelog](CHANGELOG.md)

> **Public-launch requirement:** obtain written confirmation from FatSecret before scaling the bot
> publicly. The current FatSecret Platform API terms do not explicitly authorize sending even
> minimized FatSecret content to an independent AI processor.

[Powered by fatsecret Platform API](https://platform.fatsecret.com)

## License

Released under the [MIT License](LICENSE). The project itself is developed and operated on a
non-commercial basis; the MIT license does not restrict third-party commercial reuse.
