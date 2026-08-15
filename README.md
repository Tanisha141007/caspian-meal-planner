# Caspian Meal-Planning Workflow

Weekly/monthly Indian meal charts, generated per household from a recipe
universe + diet profile, sent to the family's cook by text every morning
with ingredients, quantities, and portion sizes - and updated from the
cook's replies.

## What Caspian actually does here

[Caspian](https://www.trycaspianai.com/docs/) is a messaging **transport**
layer, not a planning or knowledge engine: one `on_message` handler, one
`message.reply()` / `send_message()` / `initiate()`, routed to whichever
live channel the message came from.
It has no concept of recipes, diets, or meal plans. All of that - the
recipe universe, the household's diet profile, the weekly/monthly
generation, and the text that goes out - is this app; Caspian only carries
the final message to the cook's phone and carries their reply back.

**Channel status:** Always check Caspian's live channel endpoint before
connecting a channel:

```bash
curl -s https://api.trycaspianai.com/v1/channels \
  -H "Authorization: Bearer $CASPIAN_API_KEY"
```

As of this build, the hosted gateway lists email, Discord, Slack, X, Telegram,
phone/SMS through Twilio or Telnyx, Bluesky, GMeet, Zulip, and Linear.
WhatsApp is not live on this gateway yet, even though SDK methods may exist
locally, so this project must not try to connect it. The app defaults to
**SMS via your own Twilio number** for cook notifications.

## Architecture

```
Recipe universe (app/data/recipes_seed.json, 36 dishes)
Household diet profile (app/models.py: Household)
            |
            v
Meal-plan generator (app/meal_planner/generator.py, Claude)
  - filters recipes by diet/allergy/dislikes
  - avoids repeats from the last 14 days
  - writes a MealPlan + MealPlanItem per day/slot
            |
            v
Scheduler (app/scheduler/jobs.py, APScheduler)
  - Sun 20:00  -> generate next week's chart per household
  - 1st, 08:00 -> aggregate the month into one ingredient shopping list
  - daily, per household send_time -> format + send today's meals
            |
            v
Caspian CommClient (app/messaging/handler.py)
  - send_message() / initiate() pushes today's meals to the cook
  - on_message() reads the cook's reply, classifies it with Claude
    (dislike / swap request / ingredient issue / confirmation / question),
    logs it as Feedback, and acks it
```

## Data model

- **Household** - one row per family: cook's phone, diet type, allergies,
  dislikes, preferred cuisines, spice level, family size, kids count,
  free-text notes (fed straight into the LLM prompt), and the
  `caspian_conversation_id` once the cook has texted in.
- **Recipe** - one dish: region, cuisine, meal types, diet, spice level,
  tags, and ingredients scaled to **1 serving** (multiplied by
  `portion_servings` at send time). This is the "training data" from the
  brief: retrieval + context handed to Claude on every generation call,
  not a fine-tuned model.
- **MealPlan / MealPlanItem** - a week (or four weeks, for "monthly") of
  `date x meal_slot -> [recipe_ids]`, e.g. lunch = dal + rice + roti.
- **Feedback** - every inbound cook reply plus Claude's read on what it meant.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in CASPIAN_API_KEY, ANTHROPIC_API_KEY, Twilio creds
```

Get `CASPIAN_API_KEY` from [dashboard.trycaspianai.com](https://dashboard.trycaspianai.com)
and `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com).
For SMS you need your own Twilio number + Account SID + Auth Token
(console.twilio.com), and its inbound webhook pointed at Caspian per
[the SMS docs](https://www.trycaspianai.com/docs/) (`connect_phone` returns
the phone connection used by outbound sends).

## Running it

```bash
python scripts/seed_db.py                                   # load the recipe universe
python scripts/onboard_household.py --name "Malani" \
    --cook-name "Radha" --cook-phone "+919812345678" \
    --diet-type veg --family-size 4 --kids-count 1 \
    --spice-level mild --allergies peanut \
    --preferred-cuisines gujarati punjabi

python scripts/generate_week.py 1                            # weekly chart for household 1
python scripts/send_today.py 1                                # send today's meals now (manual test)

python -m app.main                                             # run the real service:
                                                                 #   listens for cook replies
                                                                 #   + runs the weekly/monthly/daily cron jobs
```

## Known simplifications (buildathon scope, not production)

- `_extract_phone()` in `app/messaging/handler.py` guesses the shape of
  `message.sender` for the phone channel - confirm the exact keys against
  a real inbound Twilio message once it's wired up.
- The daily cron groups households by `Household.send_time`, but jobs are
  only registered at `start_scheduler()` startup - restart the process
  after adding a household with a send_time that doesn't already have a job.
- No auth/API layer for managing households - it's CLI scripts + direct
  DB access. Fine for one buildathon demo, not for multiple operators.
