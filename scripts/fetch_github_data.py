#!/usr/bin/env python3
"""Collect a complete GitHub snapshot without changing assets on API failure."""

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
QUERY = """
query Profile($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    login
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}
"""
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def api(path, payload=None):
    """Use the workflow token, or an existing gh login on a developer machine."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        request = Request(
            "https://api.github.com/" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json",
                     "User-Agent": "fabiolrocha-profile"},
        )
        with urlopen(request, timeout=45) as response:
            return json.load(response)
    command = ["gh", "api", path]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command, input=json.dumps(payload) if payload is not None else None,
        text=True, capture_output=True, timeout=60, check=True,
    )
    return json.loads(result.stdout)


def normalize(calendar, start, end):
    """Reject incomplete calendars rather than displaying fabricated zeroes."""
    days = []
    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            when = date.fromisoformat(day["date"])
            if start <= when <= end:
                count = day["contributionCount"]
                if type(count) is not int or count < 0:
                    raise ValueError("Invalid contribution count")
                level = LEVELS[day["contributionLevel"]]
                if (count == 0) != (level == 0):
                    raise ValueError("Contribution color does not match its count")
                days.append({"date": when.isoformat(), "count": count, "level": level})
    days.sort(key=lambda day: day["date"])
    expected = [(start + timedelta(days=i)).isoformat()
                for i in range((end - start).days + 1)]
    if [day["date"] for day in days] != expected:
        raise ValueError("GitHub returned an incomplete or duplicate calendar")
    if sum(day["count"] for day in days) != calendar["totalContributions"]:
        raise ValueError("Contribution total does not match the calendar")
    return days


def collect(username, today):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        raise ValueError("Invalid GitHub username")
    start = today - timedelta(days=364)
    response = api("graphql", {"query": QUERY, "variables": {
        "login": username,
        "from": datetime.combine(start, time.min, timezone.utc).isoformat(),
        "to": datetime.combine(today, time(23, 59, 59), timezone.utc).isoformat(),
    }})
    if response.get("errors"):
        raise ValueError("GitHub GraphQL returned errors")
    user = response["data"]["user"]
    if not user or user["login"].lower() != username.lower():
        raise ValueError("GitHub user could not be verified")
    days = normalize(user["contributionsCollection"]["contributionCalendar"], start, today)
    public = api("users/" + username)
    if public["login"].lower() != username.lower():
        raise ValueError("Public profile does not match the calendar")
    repositories = public["public_repos"]
    if type(repositories) is not int or repositories < 0:
        raise ValueError("Invalid public repository count")
    return {"username": username, "as_of": today.isoformat(), "timezone": "UTC",
            "from": start.isoformat(), "to": today.isoformat(),
            "public_repositories": repositories, "days": days}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/github.json")
    args = parser.parse_args()
    try:
        profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
        snapshot = collect(profile["username"], datetime.now(timezone.utc).date())
        content = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Never echo API payloads or authentication details into Actions logs.
        print(f"Collection failed ({type(error).__name__}); previous data and assets retained.",
              file=sys.stderr)
        return 1
    print(f"Collected {len(snapshot['days'])} days for {snapshot['username']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
