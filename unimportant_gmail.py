"""Find senders of labeled mail without an existing Gmail filter, and create filters for them."""

import argparse
import csv
import os
import re
import sys
import time
from email.utils import parseaddr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]

DEFAULT_LABEL = "↓ Unimportant"
DEFAULT_WINDOW = "newer_than:14d"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CREDS = os.path.join(HERE, "credentials.json")
DEFAULT_TOKEN = os.path.join(HERE, "token.json")

RETRY_STATUSES = {429, 500, 502, 503, 504}
METADATA_BATCH_SIZE = 100


def _retry(call, max_attempts=5, base_delay=1.0):
    """Execute call() with exponential backoff on transient Gmail API errors."""
    for attempt in range(max_attempts):
        try:
            return call()
        except HttpError as e:
            status = getattr(getattr(e, "resp", None), "status", None)
            if status in RETRY_STATUSES and attempt < max_attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise


def authenticate(creds_path, token_path, allow_browser_flow=True):
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not allow_browser_flow:
                sys.exit(
                    f"Interactive OAuth required but --no-auth-flow is set. "
                    f"Run interactively once to refresh {token_path}."
                )
            if not os.path.exists(creds_path):
                sys.exit(
                    f"Missing {creds_path}. Download OAuth client (Desktop) JSON "
                    "from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        os.chmod(token_path, 0o600)
    return build("gmail", "v1", credentials=creds)


def parse_from_criterion(from_val):
    """Parse a Gmail filter 'from' criterion into (exact_emails, domains).

    exact_emails: addresses that must match the sender exactly (e.g. billing@example.com).
    domains:      domains where any sender at that domain is covered (e.g. example.com).

    Domain-style coverage is added only for tokens that explicitly look like a domain
    filter ('@example.com' or bare 'example.com'). An exact-address filter like
    'billing@example.com' does NOT add example.com to the domain set.
    """
    exact_emails = set()
    domains = set()

    if not from_val:
        return exact_emails, domains

    val = from_val
    for ch in '(){},|"\'':
        val = val.replace(ch, " ")
    val = re.sub(r"\bOR\b", " ", val, flags=re.IGNORECASE)

    for raw in val.split():
        t = raw.strip().lower()
        if not t or t.startswith("-"):
            continue
        if t.startswith("@"):
            dom = t[1:]
            if dom and "." in dom:
                domains.add(dom)
        elif "@" in t:
            local, _, dom = t.partition("@")
            if local and dom:
                exact_emails.add(t)
        elif "." in t:
            domains.add(t)

    return exact_emails, domains


def parse_query_criterion(query_val):
    """Parse sender coverage from Gmail search query syntax.

    This intentionally extracts only explicit from: terms. A bare email address in
    a has-the-words query may just be body text, so it should not be treated as a
    sender filter unless Gmail's search field scopes it with from:.
    """
    exact_emails = set()
    domains = set()

    if not query_val:
        return exact_emails, domains

    # Handles forms like:
    #   from:a@example.com
    #   {from:a@example.com from:b@example.com}
    #   from:(a@example.com OR b@example.com)
    #   from:{a@example.com b@example.com}
    pattern = re.compile(r"from:(\{[^}]+\}|\([^)]+\)|\"[^\"]+\"|'[^']+'|[^\s}]+)", re.I)
    for match in pattern.finditer(query_val):
        exact, parsed_domains = parse_from_criterion(match.group(1))
        exact_emails |= exact
        domains |= parsed_domains

    return exact_emails, domains


def collect_filter_targets(filters):
    """Aggregate exact emails/domains across filter sender criteria."""
    all_exact = set()
    all_domains = set()
    for f in filters:
        criteria = f.get("criteria", {})
        exact, domains = parse_from_criterion(criteria.get("from", ""))
        query_exact, query_domains = parse_query_criterion(criteria.get("query", ""))
        all_exact |= exact
        all_exact |= query_exact
        all_domains |= domains
        all_domains |= query_domains
    return all_exact, all_domains


def is_sender_filtered(email, exact_emails, domains):
    if email in exact_emails:
        return True
    if "@" in email:
        if email.split("@", 1)[1] in domains:
            return True
    return False


def find_label_id(svc, name):
    labels = _retry(lambda: svc.users().labels().list(userId="me").execute()).get("labels", [])
    for l in labels:
        if l["name"] == name:
            return l["id"]
    sys.exit(f"Label '{name}' not found in account.")


def fetch_senders(svc, label_id, window):
    senders = {}
    page_token = None
    n = 0
    while True:
        resp = _retry(
            lambda: svc.users().messages().list(
                userId="me",
                labelIds=[label_id],
                q=window,
                pageToken=page_token,
                maxResults=500,
            ).execute()
        )
        msgs = resp.get("messages", [])
        message_ids = [m["id"] for m in msgs]
        for full in fetch_message_metadata(svc, message_ids):
            headers = {
                h["name"]: h["value"]
                for h in full.get("payload", {}).get("headers", [])
            }
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


def fetch_message_metadata(svc, message_ids):
    """Fetch From/Subject metadata for message_ids using Gmail batch requests."""
    if not message_ids:
        return []

    out = []
    for start in range(0, len(message_ids), METADATA_BATCH_SIZE):
        chunk = message_ids[start:start + METADATA_BATCH_SIZE]
        responses = {}
        errors = {}

        def callback(request_id, response, exception):
            if exception is None:
                responses[request_id] = response or {}
            else:
                errors[request_id] = exception

        def execute_batch():
            responses.clear()
            errors.clear()
            batch = svc.new_batch_http_request(callback=callback)
            for message_id in chunk:
                batch.add(
                    svc.users().messages().get(
                        userId="me",
                        id=message_id,
                        format="metadata",
                        metadataHeaders=["From", "Subject"],
                    ),
                    request_id=message_id,
                )
            return batch.execute()

        _retry(execute_batch)

        for message_id, error in errors.items():
            status = getattr(getattr(error, "resp", None), "status", None)
            if isinstance(error, HttpError) and status in RETRY_STATUSES:
                responses[message_id] = _retry(
                    lambda mid=message_id: svc.users().messages().get(
                        userId="me",
                        id=mid,
                        format="metadata",
                        metadataHeaders=["From", "Subject"],
                    ).execute()
                )
            else:
                raise error

        out.extend(responses[message_id] for message_id in chunk if message_id in responses)

    return out


def fetch_existing_filters(svc):
    return _retry(
        lambda: svc.users().settings().filters().list(userId="me").execute()
    ).get("filter", [])


def create_filter(svc, criteria, label_id):
    body = {
        "criteria": criteria,
        "action": {"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]},
    }
    return _retry(
        lambda: svc.users().settings().filters().create(userId="me", body=body).execute()
    )


def filter_criteria_for_senders(emails):
    if len(emails) == 1:
        return {"from": emails[0]}
    query = "{" + " ".join(f"from:{email}" for email in emails) + "}"
    return {"query": query}


def chunks(items, size):
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", default=DEFAULT_LABEL,
                   help=f"Label name to scan. Default: {DEFAULT_LABEL!r}")
    p.add_argument("--window", default=DEFAULT_WINDOW,
                   help=f"Gmail search window. Default: {DEFAULT_WINDOW!r}")
    p.add_argument("--credentials", default=DEFAULT_CREDS,
                   help="Path to OAuth client JSON.")
    p.add_argument("--token", default=DEFAULT_TOKEN,
                   help="Path to cached token JSON.")
    p.add_argument("--output-dir", default=HERE,
                   help="Where senders.csv and diff.csv are written.")
    p.add_argument("--apply", action="store_true",
                   help="Actually create filters. Default is dry-run.")
    p.add_argument("--group-size", type=int, default=25,
                   help="Group this many missing senders into one Gmail query filter. Use 1 for one filter per sender.")
    p.add_argument("--no-auth-flow", action="store_true",
                   help="Exit with an error instead of opening a browser if interactive auth is needed. Use this in cron.")
    args = p.parse_args()
    if args.group_size < 1:
        p.error("--group-size must be at least 1")
    return args


def main():
    args = parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    senders_csv = os.path.join(args.output_dir, "senders.csv")
    diff_csv = os.path.join(args.output_dir, "diff.csv")

    print("Authenticating...", file=sys.stderr)
    svc = authenticate(args.credentials, args.token, allow_browser_flow=not args.no_auth_flow)

    print(f"Looking up '{args.label}' label...", file=sys.stderr)
    label_id = find_label_id(svc, args.label)
    print(f"  label id: {label_id}", file=sys.stderr)

    print(f"Fetching messages with label in {args.window}...", file=sys.stderr)
    senders = fetch_senders(svc, label_id, args.window)
    print(f"  unique senders: {len(senders)}", file=sys.stderr)

    print("Fetching existing filters...", file=sys.stderr)
    filters = fetch_existing_filters(svc)
    exact_emails, domains = collect_filter_targets(filters)
    print(
        f"  existing filters: {len(filters)}  "
        f"(exact emails: {len(exact_emails)}, domains: {len(domains)})",
        file=sys.stderr,
    )

    missing = []
    covered = []
    for email, info in sorted(senders.items(), key=lambda kv: -kv[1]["count"]):
        if is_sender_filtered(email, exact_emails, domains):
            covered.append(info)
        else:
            missing.append(info)

    with open(senders_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["email", "count", "sample_subject", "has_filter"])
        for info in sorted(senders.values(), key=lambda i: -i["count"]):
            has = is_sender_filtered(info["email"], exact_emails, domains)
            w.writerow([info["email"], info["count"], info["sample_subject"], "yes" if has else "no"])

    with open(diff_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["email", "count", "sample_subject"])
        for info in missing:
            w.writerow([info["email"], info["count"], info["sample_subject"]])

    print()
    print(f"Senders WITH existing filter:    {len(covered)}")
    print(f"Senders WITHOUT a filter:        {len(missing)}")
    print()
    print(f"  Full sender list:  {senders_csv}")
    print(f"  Filter candidates: {diff_csv}")
    print()

    if not missing:
        print("Nothing to do.")
        return

    if not args.apply:
        print("Dry run. Re-run with --apply to create filters.")
        planned_filters = len(list(chunks(missing, args.group_size)))
        print(f"Would create {planned_filters} Gmail filter(s) for {len(missing)} sender(s).")
        print(f"Preview (top 20 of {len(missing)}):")
        for info in missing[:20]:
            print(f"  [{info['count']:>3}] {info['email']}  ({info['sample_subject'][:60]})")
        return

    groups = list(chunks(missing, args.group_size))
    print(f"Creating {len(groups)} filters for {len(missing)} senders: apply '{args.label}' + skip inbox...")
    created = 0
    errors = 0
    for group in groups:
        emails = [info["email"] for info in group]
        try:
            create_filter(svc, filter_criteria_for_senders(emails), label_id)
            created += 1
            if len(emails) == 1:
                print(f"  + {emails[0]}")
            else:
                print(f"  + grouped filter for {len(emails)} senders")
        except HttpError as e:
            errors += 1
            label = emails[0] if len(emails) == 1 else f"{len(emails)}-sender group starting {emails[0]}"
            print(f"  ! {label} :: {e}")
    print()
    print(f"Created: {created}.  Errors: {errors}.")


if __name__ == "__main__":
    main()
