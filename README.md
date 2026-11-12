# meme-pipeline

A tool for humor channels. It finds the funniest posts in other channels, lets
an editor choose memes quickly in a Telegram bot, turns text jokes into
pictures and publishes everything on a weekly schedule.

This is a clean version of my real tool. All data here are examples.

## How it works

```
Telegram exports → import → scores → editor bot → text to picture → schedule → publish
```

1. **Import.** Read posts, photos and reactions from other channels.
2. **Scores.** Find out which posts were really popular.
3. **Editor bot.** Show the best memes one by one with Approve and Reject buttons.
4. **Text to picture.** Turn text jokes into square images.
5. **Schedule.** Give every post a day and a time.
6. **Publish.** Send posts when their time comes (run it with cron).

## The hard parts

**Fair popularity score.** A big channel gets more reactions on every post, so
raw numbers do not help. Each post is compared with the average post of the
same channel in the same month. Score 1.0 is a normal post, 3.0 is three times
better than normal. There is also a separate score for laughing reactions only.

**Same picture, different file.** Popular memes are reposted many times:
smaller, with another watermark, saved with lower quality. The tool makes a
short "fingerprint" of each image (dHash). Copies have almost the same
fingerprint, so the editor never sees the same meme twice.

**Choosing donors.** Each channel has its own list of donor channels with
weights. A donor with weight 3 is shown three times more often, but the order
is still random.

**Text on images.** The font size is chosen so the text fills the space. Lines
are made about the same length, and short words like "in" or "and" never stay
at the end of a line.

**Schedule.** Each weekday has its own slots, for example meme, story, meme.
If one type of post runs out, another type takes its slot, and the tool tells
you what is missing.

## Setup

Python 3.10 or newer.

```bash
pip install -r requirements-dev.txt
cp .env.example .env
cp targets.example.json targets.json
```

In `.env` add the Telegram bot token, your user id (`ADMIN_IDS`) and a font
file. In `targets.json` describe your channels, donors and weekly slots.

## Run

```bash
python -m meme_pipeline ingest exports/
python -m meme_pipeline top
python -m meme_pipeline curate
python -m meme_pipeline add-text stories.txt --target everyday-humor --kind story
python -m meme_pipeline render --target everyday-humor --kind story
python -m meme_pipeline schedule --target everyday-humor --start 2025-01-01
python -m meme_pipeline publish
```

In `examples/exports` one picture is a copy of another, so you can see the
repost filter work.

Tests: `pytest`
