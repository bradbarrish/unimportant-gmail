"""Find senders of '↓ Unimportant'-labeled mail without an existing Gmail filter, and create filters for them."""

import argparse
import csv
import os
import sys
from email.utils import parseaddr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.labels",
]

LABEL_NAME = "↓ Unimportant"
TIME_WINDOW = "newer_than:14d"

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS_PATH = os.path.join(HERE, "credentials.json")
TOKEN_PATH = os.path.join(HERE, "token.json")
SENDERS_CSV = os.path.join(HERE, "senders.csv")
DIFF_CSV = os.path.join(HERE, "diff.csv")


def authenticate():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_PATH):
                sys.exit(
                    f"Missing {CREDS_PATH}. Download OAuth client (Desktop) JSON "
                    "from Google Cloud Console and save it as credentials.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def find_label_id(svc, name):
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"] == name:
            return l["id"]
    sys.exit(f"Label '{name}' not found in account.")


def fetch_senders(svc, label_id):
    """Return dict: lowercase_email -> {'email': email, 'count': n, 'sample_subject': str}."""
    senders = {}
    page_token = None
    n = 0
    while True:
        resp = (
            svc.users()
            .messages()
            .list(
                userId="me",
                labelIds=[label_id],
                q=TIME_WINDOW,
                pageToken=page_token,
                maxResults=500,
            )
            .execute()
        )
        msgs = resp.get("messages", [])
        for m in msgs:
            full = (
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=m["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject"],
                )
                .execute()
            )
            headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
            _, addr = parseaddr(headers.get("From", ""))
            if not addr or "@" not in addr:
                continue
            key = addr.lower().strip()
            if key not in senders:
                senders[key] = {
                    "email": key,
                    "count": 0,
                    "sample_subject": headers.get("Subject", ""),
                }
            senders[key]["count"] += 1
            n += 1
        print(f"  fetched {n} messages...", file=sys.stderr)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return senders


def fetch_existing_filters(svc):
    """Return list of filter dicts."""
    resp = svc.users().settings().filters().list(userId="me").execute()
    return resp.get("filter", [])


def existing_from_emails(filters):
    """Return set of lowercase email addresses appearing in any filter's 'from' criterion."""
    emails = set()
    for f in filters:
        crit = f.get("criteria", {})
        from_val = crit.get("from", "")
        if not from_val:
            continue
        # Filter "from" can be a single address, a list with OR, or contain partial matches.
        # Extract anything that looks like an email and normalize.
        tokens = (
            from_val.replace("(", " ")
            .replace(")", " ")
            .replace("{", " ")
            .replace("}", " ")
            .replace(",", " ")
            .replace("|", " ")
            .replace("OR", " ")
            .split()
        )
        for t in tokens:
            t = t.strip().strip('"').strip("'").lower()
            if not t or t.startswith("-"):
                continue
            if "@" in t:
                emails.add(t)
                # Also store the bare domain form so '@domain.com' matches by-domain checks.
                domain = t.split("@", 1)[1]
                if domain and "." in domain:
                    emails.add(domain)
            elif "." in t:
                # Bare domain filter like "amazon.com"
                emails.add(t)
    return emails


def sender_already_filtered(email, filter_emails):
    """A sender is considered already filtered if their exact email appears, OR their domain appears."""
    if email in filter_emails:
        return True
    domain = email.split("@", 1)[1] if "@" in email else ""
    if domain and domain in filter_emails:
        return True
    return False


def create_filter(svc, email, label_id):
    body = {
        "criteria": {"from": email},
        "action": {
            "addLabelIds": [label_id],
            "removeLabelIds": ["INBOX"],
        },
    }
    return svc.users().settings().filters().create(userId="me", body=body).execute()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Actually create filters (default: dry-run).")
    args = p.parse_args()

    print("Authenticating...", file=sys.stderr)
    svc = authenticate()

    print(f"Looking up '{LABEL_NAME}' label...", file=sys.stderr)
    label_id = find_label_id(svc, LABEL_NAME)
    print(f"  label id: {label_id}", file=sys.stderr)

    print(f"Fetching messages with label in {TIME_WINDOW}...", file=sys.stderr)
    senders = fetch_senders(svc, label_id)
    print(f"  unique senders: {len(senders)}", file=sys.stderr)

    print("Fetching existing filters...", file=sys.stderr)
    filters = fetch_existing_filters(svc)
    filter_emails = existing_from_emails(filters)
    print(f"  existing filters: {len(filters)}  (with 'from' addresses: {len(filter_emails)})", file=sys.stderr)

    missing = []
    covered = []
    for email, info in sorted(senders.items(), key=lambda kv: -kv[1]["count"]):
        if sender_already_filtered(email, filter_emails):
            covered.append(info)
        else:
            missing.append(info)

    with open(SENDERS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["email", "count", "sample_subject", "has_filter"])
        for info in sorted(senders.values(), key=lambda i: -i["count"]):
            has = sender_already_filtered(info["email"], filter_emails)
            w.writerow([info["email"], info["count"], info["sample_subject"], "yes" if has else "no"])

    with open(DIFF_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["email", "count", "sample_subject"])
        for info in missing:
            w.writerow([info["email"], info["count"], info["sample_subject"]])

    print()
    print(f"Senders WITH existing filter:    {len(covered)}")
    print(f"Senders WITHOUT a filter:        {len(missing)}")
    print()
    print(f"  Full sender list:  {SENDERS_CSV}")
    print(f"  Filter candidates: {DIFF_CSV}")
    print()

    if not missing:
        print("Nothing to do.")
        return

    if not args.apply:
        print("Dry run. Re-run with --apply to create filters.")
        print(f"Preview (top 20 of {len(missing)}):")
        for info in missing[:20]:
            print(f"  [{info['count']:>3}] {info['email']}  ({info['sample_subject'][:60]})")
        return

    print(f"Creating {len(missing)} filters: apply '{LABEL_NAME}' + skip inbox...")
    created = 0
    errors = 0
    for info in missing:
        try:
            create_filter(svc, info["email"], label_id)
            created += 1
            print(f"  + {info['email']}")
        except HttpError as e:
            errors += 1
            print(f"  ! {info['email']} :: {e}")
    print()
    print(f"Created: {created}.  Errors: {errors}.")


if __name__ == "__main__":
    main()
