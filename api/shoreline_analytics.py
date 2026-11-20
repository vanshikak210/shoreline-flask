"""
Pure aggregation for the Shoreline admin analytics route (GET /api/shoreline/admin/analytics).

Copy this file next to shoreline.py as  api/shoreline_analytics.py . It has no Flask or
database imports, so tests can call build_analytics() with plain values
(tests/test_shoreline_analytics.py). shoreline.py loads the rows and passes them in.
"""

from collections import Counter, defaultdict

TOP_VOLUNTEER_LIMIT = 10
SURVEY_CHOICES = ("volunteer", "donate", "none")


def _counted(counter):
    """[{label, count}] largest first, ties by label, so output is deterministic."""
    return [{"label": label, "count": count}
            for label, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def build_analytics(member_ids, signup_dates, survey_choices, profiles, hours, names):
    """
    member_ids      ids of every user with any Shoreline sign-up, survey, profile or hours row
    signup_dates    datetimes from shoreline_signups (only sign-ups made since tracking began)
    survey_choices  one choice per user: "volunteer" | "donate" | "none"
    profiles        dicts with "neighborhood", "availability" and "interests" (a list)
    hours           dicts with "user_id", "activity" and "hours"
    names           {user_id: display name} for users who logged hours
    """
    by_month = Counter(d.strftime("%Y-%m") for d in signup_dates if d)

    survey = {choice: 0 for choice in SURVEY_CHOICES}
    for choice in survey_choices:
        if choice in survey:
            survey[choice] += 1

    neighborhoods = Counter(p.get("neighborhood") for p in profiles if p.get("neighborhood"))
    availability = Counter(p.get("availability") for p in profiles if p.get("availability"))
    interests = Counter(i for p in profiles for i in (p.get("interests") or []) if i)

    by_activity = defaultdict(float)
    per_user = defaultdict(lambda: {"hours": 0.0, "shifts": 0})
    for entry in hours:
        amount = float(entry.get("hours") or 0)
        by_activity[entry.get("activity") or "Other"] += amount
        per_user[entry["user_id"]]["hours"] += amount
        per_user[entry["user_id"]]["shifts"] += 1

    top = sorted(per_user.items(), key=lambda item: (-item[1]["hours"], str(names.get(item[0], ""))))
    top_volunteers = [
        {"name": names.get(user_id, "Unknown"), "hours": round(totals["hours"], 2), "shifts": totals["shifts"]}
        for user_id, totals in top[:TOP_VOLUNTEER_LIMIT]
    ]

    dated = [d for d in signup_dates if d]
    return {
        "members": len(set(member_ids)),
        "signups": {
            "tracked_since": min(dated).isoformat() if dated else None,
            "by_month": [{"month": month, "count": by_month[month]} for month in sorted(by_month)],
        },
        "survey": survey,
        "hours": {
            "total": round(sum(by_activity.values()), 2),
            "shifts": sum(t["shifts"] for t in per_user.values()),
            "volunteers": len(per_user),
            "by_activity": [{"label": label, "hours": round(total, 2)}
                            for label, total in sorted(by_activity.items(), key=lambda item: (-item[1], item[0]))],
            "top_volunteers": top_volunteers,
        },
        "neighborhoods": _counted(neighborhoods),
        "availability": _counted(availability),
        "interests": _counted(interests),
    }
