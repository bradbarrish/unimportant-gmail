# gmail-filters

A learning loop for keeping your Gmail inbox personal-only.

If you label noise — either with a manual click or via a catch-all filter — this script turns that label into a permanent Gmail filter. The next time the same sender shows up, Gmail handles it before you ever see it.

## The idea

Most inboxes are ~98% bulk: newsletters, receipts, marketing, notifications, automated mail. If you want only personal email in your inbox, you have to filter aggressively. Doing that by hand at scale is exhausting. This script automates the loop:

1. You designate a label as "this should never reach my inbox" — by default `↓ Unimportant`.
2. Anything that lands with that label (whether you applied it manually, or a catch-all filter did) gets noticed.
3. The script reads your existing filters and figures out which of those senders are not yet filtered.
4. With `--apply`, it creates a Gmail filter for each missing sender so it skips the inbox in future.

Over time the inbox quiets down, and the only things still landing in it are senders you genuinely want to hear from.

## What the script does

1. Authenticates to Gmail via OAuth (read messages + manage filters scopes).
2. Pulls every message under the chosen label in the last 14 days and dedupes the senders.
3. Lists your existing filters and extracts the addresses + domains they target.
4. Diffs (2) against (3). Anything not already covered is a candidate.
5. Writes a report and two CSVs (`senders.csv`, `diff.csv`). With `--apply`, creates a new Gmail filter for each candidate that applies the label and removes `INBOX`.

## Prerequisites

- Python 3.10 or newer
- A Google account with the Gmail you want to manage
- The label you want to filter into already exists in your Gmail (default: `↓ Unimportant`)

## One-time Google Cloud setup

Gmail requires an OAuth client. This is free and takes about five minutes.

### 1. Create or select a project

Go to <https://console.cloud.google.com>. Use any existing project, or click the project picker in the top bar and choose **New Project**. Name it whatever you want.

### 2. Enable the Gmail API

Open <https://console.cloud.google.com/apis/library/gmail.googleapis.com>, make sure your project is selected, and click **Enable**.

### 3. Configure the OAuth consent screen

Open <https://console.cloud.google.com/apis/credentials/consent>.

- User type: **External**
- App name: anything (e.g. `gmail-filters`)
- User support email: your own
- Developer contact: your own
- Scopes: leave empty — the script declares them at runtime
- Test users: **add the Google account whose Gmail you want to filter**. Without this step you'll hit "access blocked" during OAuth.

You can leave the app in **Testing** mode. You don't need to publish it.

### 4. Create OAuth client credentials

Open <https://console.cloud.google.com/apis/credentials>, then **Create Credentials → OAuth client ID**.

- Application type: **Desktop app**
- Name: anything (e.g. `gmail-filters CLI`)
- Click **Create**, then **Download JSON**

### 5. Save the JSON

Move the downloaded file into this directory and rename it to `credentials.json`. It is git-ignored.

## Install

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## First run

```sh
.venv/bin/python gmail_filters.py
```

This is a dry run. The first time, your browser will pop open for OAuth — pick the Google account you added as a test user, click through the "Google hasn't verified this app" warning (it's your own app), and grant the scopes. A refresh token will be cached to `token.json` so subsequent runs are non-interactive.

You'll get a report showing how many candidate senders the script found. Look at `senders.csv` and `diff.csv` to sanity-check.

When you're ready to actually create the filters:

```sh
.venv/bin/python gmail_filters.py --apply
```

You can re-run any time — the script is idempotent. It only creates filters for senders it can't find an existing match for.

## CLI options

```text
--label LABEL          Label name to scan. Default: '↓ Unimportant'
--window WINDOW        Gmail search window. Default: 'newer_than:14d'
--credentials PATH     OAuth client JSON. Default: ./credentials.json
--token PATH           Cached token JSON. Default: ./token.json
--output-dir DIR       Where senders.csv and diff.csv land. Default: script dir
--apply                Actually create filters (default is dry-run).
--no-auth-flow         Exit with an error instead of opening a browser if interactive
                       auth is needed. Use this in cron.
```

The filter action — `apply LABEL + remove INBOX` — is hardcoded. If you want different behavior (delete on arrival, archive without label, apply a different label), edit the `create_filter` function. It's a one-line dict.

## Tests

```sh
.venv/bin/python test_gmail_filters.py
```

The tests cover the filter-criterion parser and the sender-matching logic. These are the parts of the code where a subtle bug can cause the script to silently skip filters that should be created. If you touch `parse_from_criterion` or `is_sender_filtered`, run the tests.

## How sender matching works

The script parses every existing filter's `from:` criterion into two sets:

- **Exact emails** — addresses where the local part is significant (e.g. `billing@example.com`).
- **Domains** — domains where any sender at that domain is covered (e.g. `example.com`, written as `@example.com` or bare `example.com` in the filter).

A sender from your `↓ Unimportant` label counts as "already filtered" if its exact address is in the exact-email set, **or** its domain is in the domain set.

Crucially, an exact-address filter like `billing@example.com` **does not** cover `alerts@example.com`. You'd want it to skip a real candidate only when you've explicitly created a domain filter for the whole company.

The parser handles `OR` (any case), curly-brace groups (`{a@x.com b@y.com}`), parens, quoted values, and negative terms.

## Running on a schedule (headless / always-on box)

The script works fine under cron. Example: daily at 6am on Linux, pulling latest code from git first.

```cron
0 6 * * * cd /home/you/gmail-filters && (echo "=== $(date) ===" && /usr/bin/git pull --quiet && /home/you/gmail-filters/.venv/bin/python gmail_filters.py --apply --no-auth-flow) >> /home/you/gmail-filters/run.log 2>&1
```

`--no-auth-flow` matters: if the refresh token ever becomes invalid, the default behavior is to open a browser to re-authenticate, which would just hang under cron. With the flag, the script exits with an error and you'll see it in the log.

For a headless box, do the OAuth dance once on a machine with a browser, then copy `token.json` over. The refresh token works on any machine until you explicitly revoke it.

If the script ever fails to refresh, it most likely means your OAuth consent screen is still in **Testing** mode and Google has expired the refresh token (this can happen if the app sits unused). Re-run interactively to mint a new one, or push the consent screen to **In production** to avoid expiry.

Transient API failures (429 rate limits, 5xx responses) are automatically retried with exponential backoff before bubbling up.

## What never gets committed

The included `.gitignore` excludes:

- `credentials.json` — OAuth client secret
- `token.json` — your access + refresh tokens
- `senders.csv`, `diff.csv` — contain sender email addresses
- `run.log` — same
- `.venv/`

If you're forking this repo, keep these excluded.
