# Caspian Meal-Planning Workflow

Weekly/monthly Indian meal charts, generated per household from a recipe
universe + diet profile, sent to the family's cook by text every morning
with ingredients, quantities, and portion sizes - and updated from the
cook's replies.

## What Caspian actually does here

[Caspian](https://www.trycaspianai.com/docs/) is a messaging **transport**
layer, not a planning or knowledge engine: one `on_message` handler, one
`message.reply()` / `send_message()` / `initiate()`, routed to whichever
channel (SMS, WhatsApp, Telegram, Slack, email, ...) the message came from.
It has no concept of recipes, diets, or meal plans. All of that - the
recipe universe, the household's diet profile, the weekly/monthly
generation, and the text that goes out - is this app; Caspian only carries
the final message to the cook's phone and carries their reply back.

**Channel status:** Caspian's docs list WhatsApp as "coming soon" (SMS,
Telegram, Slack, Discord, email are live and free; X and iMessage are paid).
The installed `caspian-sdk` package already ships `connect_whatsapp()` and a
hosted `start_whatsapp_onboarding()` flow that hits a real API endpoint and
is billed like the other paid channels - so it may already work for some
accounts even though the docs site hasn't caught up. This project defaults
to **SMS via your own Twilio number** (confirmed working) and treats
WhatsApp as a one-env-var swap (`CASPIAN_CHANNEL=whatsapp`) once you've
confirmed it's live on your account - see
[scripts/start_whatsapp_onboarding.py](scripts/start_whatsapp_onboarding.py).
The handler, formatter, and scheduler never change either way.

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
  - Mon 08:00  -> email each family the whole week + new suggestions
  - 1st, 08:00 -> aggregate the month into one ingredient shopping list
  - daily, per household send_time -> format + send today's meals
            |
            v
Caspian CommClient (app/messaging/handler.py)
  - send_message() / initiate() pushes today's meals to the cook
  - send_owner_email() mails the family their week (separate connection)
  - on_message() reads the reply - from the cook or the family - classifies
    it with the LLM (dislike / swap request / ingredient issue /
    confirmation / question), logs it as Feedback, and acks it
```

## Two audiences, two channels

The cook and the family get different things over different Caspian
connections, from the same process:

| | Cook | Family (the app's user) |
|---|---|---|
| Channel | Telegram (default), SMS, WhatsApp | Email |
| Cadence | Daily, at `Household.send_time` | Mondays, `WEEKLY_EMAIL_TIME` |
| Content | Today's meals + ingredients + portions | The whole week's chart, new dish suggestions, the week's shopping list |
| Addressed by | `link_code` handshake (the cook messages in first) | `Household.owner_email`, seeded from the Supabase login |

The email half is the one channel here that can **cold-start** a
conversation - `initiate()` - so the family never has to write in first.
That path is plain text only (caspian-sdk 0.6.4's `initiate()` takes `text`
and nothing else: no blocks, no HTML, no subject line). Once the family
replies even once, `owner_conversation_id` is stored and every later Monday
mail goes out via `send_message(blocks=...)`, which Caspian renders as real
HTML email - so the first email is plain and the rest are formatted.

The "new this week" suggestions come from the same diet- and allergy-safe
candidate set that powers the app's Discover tab
(`candidate_recipes()`), minus whatever is already on the week's chart,
ranked by the household's cuisine weighting - see `suggested_recipes()` in
`app/meal_planner/generator.py`.

To preview or send it off-schedule (rather than waiting for Monday):

```
GET  /api/households/{id}/weekly-email/preview   # renders, sends nothing
POST /api/households/{id}/weekly-email/send      # sends now
```

## Data model

- **Household** - one row per family: cook's phone, diet type, allergies,
  dislikes, preferred cuisines, spice level, family size, kids count,
  free-text notes (fed straight into the LLM prompt), and the
  `caspian_conversation_id` once the cook has texted in. `owner_email` /
  `weekly_email_enabled` / `owner_conversation_id` cover the Monday email to
  the family (see "Two audiences, two channels" below).
- **Recipe** - one dish: region, cuisine, meal types, diet, spice level,
  tags, and ingredients scaled to **1 serving** (multiplied by
  `portion_servings` at send time). This is the "training data" from the
  brief: retrieval + context handed to Claude on every generation call,
  not a fine-tuned model.
- **MealPlan / MealPlanItem** - a week (or four weeks, for "monthly") of
  `date x meal_slot -> [recipe_ids]`, e.g. lunch = dal + rice + roti.
- **Feedback** - every inbound cook reply plus Claude's read on what it meant.
- **RegionCuisineMap** - state/UT -> locally popular `cuisine_style` weights
  (`app/data/region_cuisine_seed.json`), hand-authored. Not wired into the
  planner yet - lands with Phase 3's region-popularity weighting.

## Recipe dataset

The recipe universe is seeded two ways:

- **Fixture** (default, `scripts/seed_db.py`): 36 hand-curated recipes in
  `app/data/recipes_seed.json` - fast, guaranteed-clean, used for local dev/tests.
- **Ingested** (`scripts/seed_db.py --ingested`): 4,262 recipes parsed from the
  [6000+ Indian Food Recipes Dataset](https://www.kaggle.com/datasets/kanishk307/6000-indian-food-recipes-dataset)
  (Kaggle). To regenerate:
  1. Download the dataset from Kaggle (needs a Kaggle account) and drop the
     CSV at `app/data/raw/indian_food_dataset.csv` (gitignored - it carries
     copyrighted recipe instructions text, not something to redistribute
     even privately; a one-time manual step, not fetched automatically).
  2. `python scripts/ingest_recipes.py` - parses it into
     `app/data/recipes_ingested.json` (tracked in git: structured facts only
     - names, ingredients, tags - no instructions text) and prints a
     row-count/parse-failure report.
  3. `python scripts/seed_db.py --ingested` to load it into the DB.

  Known limitations of the parsing (heuristic, not exact - see
  `app/data/ingest.py`): ~2,080 non-Indian-cuisine rows and ~529
  never-translated-to-English rows are dropped entirely; ingredient units
  are approximated into a `g/ml/pc/cup/tbsp/tsp` vocabulary (e.g. "1 clove"
  becomes `1 pc`, losing the "clove" specificity); a line with no explicit
  quantity is marked `"to taste"` rather than guessing a number; `season_tags`
  default to `all-season` (the source data carries no season signal).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in CASPIAN_API_KEY, GEMINI_API_KEY, Twilio creds
alembic upgrade head    # creates/updates the schema for whatever DATABASE_URL points at
```

Get `CASPIAN_API_KEY` from [dashboard.trycaspianai.com](https://dashboard.trycaspianai.com)
and `GEMINI_API_KEY` from [aistudio.google.com](https://aistudio.google.com)
(Google AI Studio - free tier, no card needed; set `LLM_PROVIDER=anthropic`
+ `ANTHROPIC_API_KEY` instead if you'd rather use Claude - see
`app/meal_planner/llm_client.py`).
For SMS you need your own Twilio number + Account SID + Auth Token
(console.twilio.com), and its inbound webhook pointed at Caspian per
[the SMS docs](https://www.trycaspianai.com/docs/) (`connect_phone` prints
the exact webhook URL to set).

Schema changes go through Alembic (`alembic revision --autogenerate -m "..."`,
then `alembic upgrade head`) rather than editing the DB directly - this is
what lets a populated Postgres DB pick up model changes safely. `init_db()`
(plain `Base.metadata.create_all`) still exists for quick local scripts/tests
that just need *a* working SQLite file, not a real migration history.

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
