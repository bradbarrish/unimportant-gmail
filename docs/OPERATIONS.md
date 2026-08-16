# Operations Runbook

This runbook covers day-to-day use, scheduling, verification, and rollback for `unimportant-gmail`.

The tool is intentionally conservative:

- A normal run is a dry run.
- Gmail filters are changed only when `--apply` is passed.
- The script creates filters; it does not delete existing filters.
- Local OAuth secrets, tokens, reports, logs, and virtualenv files are git-ignored.

## Regular Workflow

Install dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run a dry run:

```sh
.venv/bin/python unimportant_gmail.py
```

Inspect the output files before applying:

- `senders.csv`: every sender found under the configured label and whether the script believes it is already filtered.
- `diff.csv`: senders that are candidates for new filters.

Apply the filter changes:

```sh
.venv/bin/python unimportant_gmail.py --apply
```

Run against a different label or time window:

```sh
.venv/bin/python unimportant_gmail.py --label "Some Label" --window "newer_than:30d"
```

## Filter Grouping

By default, the tool groups up to 25 missing senders into one Gmail filter using a query criterion:

```text
{from:a@example.com from:b@example.com from:c@example.com}
```

This preserves exact sender matching while reducing filter-count growth.

Use `--group-size 1` to return to the old behavior of one Gmail filter per sender:

```sh
.venv/bin/python unimportant_gmail.py --apply --group-size 1
```

Use a smaller group size if a Gmail API request fails because the generated query is too large. The code does not currently know Gmail's undocumented maximum accepted filter-query length, so `25` is a practical default rather than a formal Gmail limit.

## Scheduling

Use `--no-auth-flow` for scheduled or headless runs. Without it, an expired or missing token can try to open an interactive browser session and hang the scheduled job.

### Cron

Example: run every day at 6am and write logs locally.

```cron
0 6 * * * cd /home/you/unimportant-gmail && /usr/bin/git pull --quiet && /home/you/unimportant-gmail/.venv/bin/python unimportant_gmail.py --apply --no-auth-flow >> /home/you/unimportant-gmail/run.log 2>&1
```

### launchd

Example user LaunchAgent for macOS:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.unimportant-gmail</string>

  <key>ProgramArguments</key>
  <array>
    <string>/path/to/unimportant-gmail/.venv/bin/python</string>
    <string>/path/to/unimportant-gmail/unimportant_gmail.py</string>
    <string>--apply</string>
    <string>--no-auth-flow</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/path/to/unimportant-gmail</string>

  <key>StartInterval</key>
  <integer>21600</integer>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/path/to/unimportant-gmail/run.log</string>

  <key>StandardErrorPath</key>
  <string>/path/to/unimportant-gmail/run.err.log</string>
</dict>
</plist>
```

Load it:

```sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.unimportant-gmail.plist
launchctl enable gui/$(id -u)/com.example.unimportant-gmail
```

Run it manually:

```sh
launchctl kickstart -k gui/$(id -u)/com.example.unimportant-gmail
```

Check it:

```sh
launchctl print gui/$(id -u)/com.example.unimportant-gmail
tail -100 run.log
tail -100 run.err.log
```

Unload it:

```sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.example.unimportant-gmail.plist
```

## Verification

Run tests:

```sh
.venv/bin/python test_unimportant_gmail.py
```

Run a syntax check:

```sh
PYTHONPYCACHEPREFIX="$PWD/__pycache__" python3 -m py_compile unimportant_gmail.py test_unimportant_gmail.py
```

Check that only intended files are staged before committing:

```sh
git status -sb
git diff --check
git diff --cached --stat
```

Check that ignored local files are still ignored:

```sh
git status --ignored -sb
```

Expected ignored private files include:

- `credentials.json`
- `token.json`
- `senders.csv`
- `diff.csv`
- `run.log`
- `.venv/`

## Rollback

Because this script creates Gmail filters, there are two different rollback surfaces: code rollback and Gmail filter rollback.

### Code Rollback

To return the local repo to the previous commit:

```sh
git log --oneline -5
git reset --hard <previous-good-commit>
```

If a commit has already been pushed and you want a non-history-rewriting rollback, revert it:

```sh
git revert <commit-to-revert>
git push
```

Prefer `git revert` for shared branches.

### Gmail Filter Rollback

This repository does not currently include a Gmail filter export/import tool. Before large changes, export or snapshot filters outside this script.

Important details:

- Gmail filter IDs are not stable restoration targets.
- Equivalent filters can be recreated from saved criteria and action data.
- If the account is at Gmail's filter limit, recreating filters may fail until enough capacity exists.
- This script only creates filters, so manual Gmail rollback means deleting the newly created filters from Gmail settings or restoring from a separate backup process.

## Troubleshooting

OAuth opens a browser during a scheduled run:

- Add `--no-auth-flow` to the scheduled command.
- Run once interactively to refresh `token.json`.

The script reports missing `credentials.json`:

- Download a Desktop OAuth client JSON from Google Cloud Console.
- Save it as `credentials.json` in the repo directory.
- Do not commit it.

The script reports that the label was not found:

- Confirm the Gmail label name exactly matches `--label`.
- The default label is `↓ Unimportant`.

Gmail returns rate limit or server errors:

- Transient 429 and 5xx responses are retried with exponential backoff.
- If failures persist, rerun later.

Gmail rejects a grouped filter:

- Retry with a smaller group size, for example `--group-size 10`.
- Use `--group-size 1` as the most conservative fallback.

The account hits Gmail's filter limit:

- Stop applying new filters.
- Review existing filters in Gmail settings.
- Consolidate or delete redundant filters only after taking a backup.
