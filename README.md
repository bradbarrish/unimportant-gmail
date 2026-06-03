# gmail-filters

Auto-create Gmail filters for the senders you've been quietly burying.

If you label noisy mail with something like `↓ Unimportant` and then often realize you'd rather just never see it again, this script does the bookkeeping: it finds every sender of recently-labeled mail that doesn't already have a filter, and creates one that applies the label and skips the inbox going forward.

## What it does

1. Authenticates to Gmail via OAuth (read-only mail + filter management scopes).
2. Fetches every message under a chosen label in the last 14 days and dedupes the senders.
3. Lists your existing filters and extracts the addresses + domains they target.
4. Diffs the two — anything in (1) that isn't matched by (3) is a candidate.
5. By default it prints a report and writes two CSVs (`senders.csv`, `diff.csv`). With `--apply`, it creates a Gmail filter for each candidate:
   - `from:` the sender's email
   - apply your label, remove `INBOX`

## Setup

You'll need a Google Cloud OAuth client (one-time, free).

1. **Create / select a project:** <https://console.cloud.google.com>
2. **Enable the Gmail API:** <https://console.cloud.google.com/apis/library/gmail.googleapis.com>
3. **Configure the OAuth consent screen:**
   - User type: External
   - Add your Google account as a Test User
4. **Create credentials:** APIs & Services → Credentials → Create → OAuth client ID → **Desktop app**. Download the JSON.
5. **Drop the JSON in this directory as `credentials.json`**.

Then:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```sh
# Dry run — report only, no changes
.venv/bin/python gmail_filters.py

# Actually create the missing filters
.venv/bin/python gmail_filters.py --apply
```

The first run opens a browser for OAuth and caches the refresh token to `token.json`. Subsequent runs are non-interactive.

## Outputs

- `senders.csv` — every sender from the labeled window, with message counts and whether a filter already covers them.
- `diff.csv` — just the candidates that would be filtered on `--apply`.
- `run.log` — when invoked from cron, you'll typically redirect here.

## Configuration

Edit the constants at the top of `gmail_filters.py`:

- `LABEL_NAME` — the label whose senders you want to auto-filter. Default: `↓ Unimportant`.
- `TIME_WINDOW` — Gmail search-style window for how far back to look. Default: `newer_than:14d`.

## Sender matching

A sender is considered "already filtered" if:

- their exact email address appears in any existing filter's `from:` criterion, **or**
- their domain (e.g. `acme.com`) appears as a bare domain or `@acme.com` in any existing filter

This means a single domain filter like `from:@acme.com` correctly covers every per-campaign tracking address Acme sends from.

## Running on a schedule

Example cron entry on a Linux box, daily at 6am:

```cron
0 6 * * * cd /home/you/gmail-filters && (echo "=== $(date) ===" && /usr/bin/git pull --quiet && /home/you/gmail-filters/.venv/bin/python gmail_filters.py --apply) >> /home/you/gmail-filters/run.log 2>&1
```

For a headless box, copy `token.json` from a machine where you've already done the OAuth dance (the refresh token works anywhere).

## Files that should never be committed

`.gitignore` already excludes them, but for the record:

- `credentials.json` — OAuth client secret
- `token.json` — your access + refresh tokens
- `senders.csv`, `diff.csv` — contain sender email addresses
- `run.log` — same
