"""Build school.ics from the Gosforth Park First School website calendar.

Keeps events for Reception and Year 4, plus school-wide events that name
no year group (holidays, training days, charity days, PTFA...).
Drops events that only name other groups (Nursery, KS1, Year 1/2/3).
"""

import datetime as dt
import html
import json
import re
import sys
import urllib.request

SITE = "https://www.gosforthpark.newcastle.sch.uk"
OUTPUT = "school.ics"
CAL_NAME = "Gosforth Park (Reception + Year 4)"

# Titles that mean "this is for Reception or Year 4 (or everyone)".
WANTED = re.compile(
    r"reception|rececption|\brec\b|\beyfs\b|\beyrs\b"
    r"|whole school|all classes|\bks2\b"
    r"|\b(?:year|yr|y)\s*4"
    r"|\b(?:year|yr|y)\s*3\s*/\s*4",
    re.I,
)
# Titles that name some other group.
OTHER = re.compile(
    r"nursery|\bks1\b|\b(?:year|yr|y)\s*[1-35-6]\b",
    re.I,
)


def keep(title):
    if WANTED.search(title):
        return True
    if OTHER.search(title):
        return False
    return True  # no year group named: treat as school-wide


def fetch_events():
    today = dt.date.today()
    start = today - dt.timedelta(days=60)
    end = today + dt.timedelta(days=400)
    url = f"{SITE}/events?start={start}&end={end}"
    # The site refuses requests without a browser-like User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def esc(text):
    return (
        text.replace("\\", "\\\\").replace(";", "\\;")
        .replace(",", "\\,").replace("\n", "\\n")
    )


def clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def fold(line):
    """Split long lines at 75 bytes, as the iCalendar format requires."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 75:
            out.append(cur.decode("utf-8"))
            cur = b" "
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def parse_dt(value):
    value = value.strip()
    if len(value) == 10:
        return dt.datetime.strptime(value, "%Y-%m-%d")
    return dt.datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S")


def to_vevent(ev, stamp):
    props = ev.get("extendedProps") or {}
    title = (ev.get("title") or "").strip()
    start = parse_dt(ev["start"])
    end = parse_dt(ev.get("end") or ev["start"])
    # Some events are marked timed but have start == end; treat as all day.
    all_day = bool(ev.get("allDay")) or start == end

    lines = ["BEGIN:VEVENT", f"UID:{ev['id']}@gosforthpark", f"DTSTAMP:{stamp}"]
    if all_day:
        first = start.date()
        last = first
        if props.get("homePageEnd"):
            last = max(first, parse_dt(props["homePageEnd"]).date())
        lines.append(f"DTSTART;VALUE=DATE:{first:%Y%m%d}")
        lines.append(f"DTEND;VALUE=DATE:{last + dt.timedelta(days=1):%Y%m%d}")
        lines.append("TRANSP:TRANSPARENT")
    else:
        lines.append(f"DTSTART;TZID=Europe/London:{start:%Y%m%dT%H%M%S}")
        lines.append(f"DTEND;TZID=Europe/London:{end:%Y%m%dT%H%M%S}")

    lines.append(f"SUMMARY:{esc(title)}")
    cats = [c.get("name", "").strip() for c in props.get("categories") or []]
    cats = [c for c in cats if c]
    desc = clean_html(props.get("description"))
    if cats:
        desc = (desc + "\n\n" if desc else "") + "Category: " + ", ".join(cats)
    if desc:
        lines.append(f"DESCRIPTION:{esc(desc)}")
    if props.get("location"):
        lines.append(f"LOCATION:{esc(props['location'].strip())}")
    lines.append("END:VEVENT")
    return lines


VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/London
BEGIN:DAYLIGHT
TZOFFSETFROM:+0000
TZOFFSETTO:+0100
TZNAME:BST
DTSTART:19700329T010000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0100
TZOFFSETTO:+0000
TZNAME:GMT
DTSTART:19701025T020000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE""".split("\n")


def build(events):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//school-calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}",
        "X-WR-TIMEZONE:Europe/London",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
        *VTIMEZONE,
    ]
    kept = 0
    for ev in sorted(events, key=lambda e: e["start"]):
        if keep(ev.get("title") or ""):
            lines += to_vevent(ev, stamp)
            kept += 1
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n", kept


def main():
    if len(sys.argv) > 1:  # test mode: read events from a file
        with open(sys.argv[1]) as f:
            events = json.load(f)
    else:
        events = fetch_events()
    if not events:
        # Don't wipe the calendar if the site returns nothing; fail loudly.
        sys.exit("No events returned by the school website. Not updating.")
    ics, kept = build(events)
    with open(OUTPUT, "w", newline="") as f:
        f.write(ics)
    print(f"Fetched {len(events)} events, kept {kept}, wrote {OUTPUT}")


if __name__ == "__main__":
    main()
