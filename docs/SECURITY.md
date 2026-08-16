# Security Notes

This project needs Gmail permissions that can read message metadata and manage Gmail filters. Treat the working directory as sensitive whenever `credentials.json`, `token.json`, or CSV reports exist locally.

## OAuth Files

`credentials.json` contains the OAuth client configuration. `token.json` contains the cached user token, including a refresh token when Google grants one.

Both files are ignored by git:

```text
credentials.json
token.json
```

Do not commit, paste, or publish either file.

If a token is exposed:

1. Revoke the app's access from the Google account security settings.
2. Delete the exposed `token.json`.
3. Re-authenticate locally to create a fresh token.

If an OAuth client secret is exposed:

1. Delete or rotate the OAuth client in Google Cloud Console.
2. Download a new Desktop OAuth client JSON.
3. Replace local `credentials.json`.

## Gmail Scopes

The script requests:

```text
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.settings.basic
```

The readonly scope is used to scan message metadata under the configured label. The settings scope is used to list and create Gmail filters.

The script does not request full mailbox modification scope and does not modify individual messages.

## Local Output Files

The generated CSVs can contain email addresses and subject samples:

```text
senders.csv
diff.csv
```

They are ignored by git and should be treated as private.

Logs from scheduled runs may also contain sender addresses, subjects, OAuth errors, or Gmail API errors. Keep log paths local and do not publish logs without review.

## Safe Commit Checklist

Before pushing:

```sh
git status -sb
git status --ignored -sb
git diff --check
git diff --cached --stat
```

Confirm that only intended source or documentation files are tracked or staged.

A quick secret-oriented scan:

```sh
rg -n "client_secret|refresh_token|access_token|private_key|AIza|ya29\\.|token\\.json|credentials\\.json" .
```

References to the filenames in documentation or code are expected. Actual token values, OAuth client secrets, API keys, private keys, local CSV contents, and Gmail data are not.

## GitHub Push Safety

A safe docs/code push should not include:

- `credentials.json`
- `token.json`
- `senders.csv`
- `diff.csv`
- `run.log`
- `.venv/`
- `__pycache__/`

The repository `.gitignore` excludes these files. Still check `git status -sb` before every push.

## Runtime Safety

Dry run first:

```sh
.venv/bin/python unimportant_gmail.py
```

Inspect `diff.csv`, then apply:

```sh
.venv/bin/python unimportant_gmail.py --apply
```

For scheduled jobs, always use:

```sh
--no-auth-flow
```

This prevents a headless job from trying to open an OAuth browser flow.

## Public Repo Hygiene

Avoid documenting personal local paths, account addresses, real sender addresses, label IDs, filter IDs, and backup filenames in committed docs unless there is a strong reason. Prefer examples such as `/path/to/unimportant-gmail`, `a@example.com`, and `com.example.unimportant-gmail`.
