"""
Shoreline survey API for the OCS Flask backend.

Drop this file into your Flask repo at  api/shoreline.py , then in main.py add:

    from api.shoreline import shoreline_api
    app.register_blueprint(shoreline_api)

and run  python main.py  (the model's table is created by db.create_all() / initUsers
on first run; if your project uses explicit init scripts, call initShorelineSurveys()).

Routes (all under /api/shoreline):
    POST /api/shoreline/signup   body {"name","uid","email","password"} — public. Creates an
                                 account WITHOUT the OCS GitHub-username check and activates it,
                                 so Shoreline visitors (not students) can sign up. Then the
                                 frontend logs in with the normal POST /api/authenticate.
    POST /api/shoreline/survey   body {"choice": "donate" | "volunteer" | "none"}  (JWT cookie)
    GET  /api/shoreline/survey   -> the caller's latest choice
    GET  /api/shoreline/survey/all  (Admin only) -> every user's latest choice
    GET  /api/shoreline/profile  -> name, email, profile fields, survey choice, hours log, totals
    PUT  /api/shoreline/profile  body any of {"name","email","phone","neighborhood",
                                 "availability","interests":[...],"bio","choice"}
    POST /api/shoreline/hours    body {"date":"YYYY-MM-DD","activity","hours","notes"}
    DELETE /api/shoreline/hours/<id>   (only your own entries)
    GET  /api/shoreline/admin/analytics  (Admin only) -> members, sign-ups per month, survey
                                 breakdown, volunteer hours, neighborhoods and interests
    GET  /api/shoreline/preferences  -> {"preferences": {...} or null} (language, theme, read aloud)
    PUT  /api/shoreline/preferences  body {"preferences": {...}} replaces the caller's saved preferences

Also copy shoreline_analytics.py to api/shoreline_analytics.py (the analytics math) and
shoreline_preferences.py to api/shoreline_preferences.py (checks saved preferences).

Admin accounts: usernames in SHORELINE_ADMIN_UIDS below are Shoreline admins. They sign up
as "Admin", and existing accounts are promoted within a minute (each worker re-checks). Everyone else
signs up as "User". Admins see the Analytics tab on the frontend.
"""

import json
import time
from datetime import date, datetime

from flask import Blueprint, g, jsonify, request
from flask_restful import Api, Resource
from sqlalchemy.exc import IntegrityError

from sqlalchemy.exc import OperationalError
from __init__ import app, db
from model.user import User

try:
    from api.shoreline_analytics import build_analytics
except ImportError:  # running from this docs folder
    from shoreline_analytics import build_analytics

try:
    from api.shoreline_preferences import PreferencesError, clean_preferences
except ImportError:  # running from this docs folder
    from shoreline_preferences import PreferencesError, clean_preferences

# The decorator moved between OCS Flask versions; support both.
try:
    from api.jwt_authorize import token_required
except ImportError:  # newer OCS Flask
    from api.authorize import token_required

shoreline_api = Blueprint("shoreline_api", __name__, url_prefix="/api/shoreline")
api = Api(shoreline_api)

VALID_CHOICES = {"donate", "volunteer", "none"}

# Shoreline admin usernames. Listing a username makes that account an admin; removing one
# does not demote it (change its role in the database for that).
SHORELINE_ADMIN_UIDS = frozenset({"nkasse12", "vanish", "toby"})


def role_for(uid):
    """Role a new Shoreline account gets: Admin for listed usernames, otherwise User."""
    return "Admin" if uid in SHORELINE_ADMIN_UIDS else "User"


ADMIN_SYNC_SECONDS = 60
_admin_roles_checked_at = None


@shoreline_api.before_app_request
def sync_admin_roles():
    """Promote listed usernames that have accounts but not the Admin role. Re-checks at most
    once a minute per worker, not just at startup, so accounts made later by any route
    (signup, scripts/add_user.py, OCS /api/user) are promoted too. A failure is logged and
    retried on the next request rather than breaking the request."""
    global _admin_roles_checked_at
    now = time.monotonic()
    if _admin_roles_checked_at is not None and now - _admin_roles_checked_at < ADMIN_SYNC_SECONDS:
        return
    try:
        users = User.query.filter(User._uid.in_(SHORELINE_ADMIN_UIDS), User._role != "Admin").all()
        for user in users:
            user._role = "Admin"
        if users:
            db.session.commit()
            app.logger.info("Shoreline: promoted %s to Admin", ", ".join(sorted(u._uid for u in users)))
        _admin_roles_checked_at = now
    except Exception:  # e.g. users table not created yet on a fresh database
        db.session.rollback()
        app.logger.exception("Shoreline: could not sync admin roles; will retry")

# Profile choices shown on /shoreline/profile; keep in sync with _data/shoreline_pages.yml.
NEIGHBORHOODS = ["Pacific Beach", "Mission Beach", "La Jolla", "Other"]
AVAILABILITY = ["Weekday mornings", "Weekday evenings", "Weekends", "Flexible"]
INTERESTS = ["Street Outreach", "Compass Station Support", "Supply Drives", "Donations"]
ACTIVITIES = ["Street Outreach", "Compass Station Support", "Supply Drive", "Event", "Other"]


class ShorelineSurvey(db.Model):
    """One row per user: what they said they wanted to do (donate / volunteer / none)."""

    __tablename__ = "shoreline_surveys"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    choice = db.Column(db.String(16), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, user_id, choice):
        self.user_id = user_id
        self.choice = choice

    def read(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "choice": self.choice,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ShorelineProfile(db.Model):
    """Shoreline-only details for a user. Name and email stay on the OCS users table."""

    __tablename__ = "shoreline_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    phone = db.Column(db.String(30), default="")
    neighborhood = db.Column(db.String(40), default="")
    availability = db.Column(db.String(40), default="")
    interests = db.Column(db.String(200), default="")  # comma-separated INTERESTS
    bio = db.Column(db.String(500), default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def read(self):
        return {
            "phone": self.phone or "",
            "neighborhood": self.neighborhood or "",
            "availability": self.availability or "",
            "interests": [i for i in (self.interests or "").split(",") if i],
            "bio": self.bio or "",
        }


class ShorelineHours(db.Model):
    """One volunteer-hours entry logged by a user."""

    __tablename__ = "shoreline_hours"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    activity = db.Column(db.String(40), nullable=False)
    hours = db.Column(db.Float, nullable=False)
    notes = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def read(self):
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "activity": self.activity,
            "hours": self.hours,
            "notes": self.notes or "",
        }


class ShorelineSignup(db.Model):
    """When a user signed up through Shoreline, so admins can chart sign-ups per month.
    Only sign-ups after this table was added have a row; older members still count in totals."""

    __tablename__ = "shoreline_signups"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ShorelinePreferences(db.Model):
    """A user's site preferences (language, theme, font, read aloud) as one JSON blob, so they
    follow the person to any device. The frontend normalizes the values when it reads them."""

    __tablename__ = "shoreline_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    data = db.Column(db.Text, nullable=False, default="{}")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SignupAPI(Resource):
    """Public signup for Shoreline visitors. Mirrors /api/user but skips the GitHub check."""

    def post(self):
        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()
        uid = str(body.get("uid", "")).strip()
        email = str(body.get("email", "")).strip()
        password = body.get("password") or ""

        if len(name) < 2:
            return {"message": "Name must be at least 2 characters"}, 400
        if len(uid) < 2 or " " in uid:
            return {"message": "Username must be at least 2 characters, no spaces"}, 400
        if "@" not in email:
            return {"message": "Enter a valid email"}, 400
        if len(password) < 6:
            return {"message": "Password must be at least 6 characters"}, 400
        if User.query.filter_by(_uid=uid).first():
            return {"message": f"Username {uid} is already taken"}, 409

        try:
            user = User(name=name, uid=uid, password=password, role=role_for(uid))
        except Exception as err:  # e.g. WeakPasswordError on newer OCS Flask
            return {"message": str(err)}, 400

        created = user.create()
        if created is None:
            return {"message": f"Could not create {uid} (duplicate?)"}, 400

        # Only the OCS fields we have; sid is required by some versions, reuse uid.
        user.update({"email": email, "sid": uid})

        ensure_survey_table()
        db.session.add(ShorelineSignup(user_id=user.id))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()  # analytics only; the account itself was created

        # Newer OCS Flask creates accounts inactive until a teacher verifies them;
        # Shoreline accounts are self-service, so activate immediately.
        if hasattr(user, "activate"):
            try:
                user.activate()
            except Exception:
                db.session.rollback()
        return jsonify({"message": "created", "uid": user.uid, "name": user.name})


def ensure_survey_table():
    """Create the Shoreline tables if missing. Cheap (checkfirst) and safe to call per
    request; OCS Flask init scripts don't know about these models, so we don't rely on them."""
    for model in (ShorelineSurvey, ShorelineProfile, ShorelineHours, ShorelineSignup, ShorelinePreferences):
        try:
            model.__table__.create(bind=db.engine, checkfirst=True)
        except OperationalError:
            # Another gunicorn worker created it between our check and our CREATE.
            db.session.rollback()


class SurveyAPI(Resource):
    @token_required()
    def post(self):
        ensure_survey_table()
        user = g.current_user
        body = request.get_json(silent=True) or {}
        choice = str(body.get("choice", "")).strip().lower()
        if choice not in VALID_CHOICES:
            return {"message": f"choice must be one of {sorted(VALID_CHOICES)}"}, 400

        row = ShorelineSurvey.query.filter_by(user_id=user.id).first()
        if row:
            row.choice = choice
        else:
            row = ShorelineSurvey(user_id=user.id, choice=choice)
            db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {"message": "could not save survey"}, 500
        return jsonify(row.read())

    @token_required()
    def get(self):
        ensure_survey_table()
        row = ShorelineSurvey.query.filter_by(user_id=g.current_user.id).first()
        if not row:
            return {"message": "no survey on file"}, 404
        return jsonify(row.read())


class SurveyAllAPI(Resource):
    @token_required("Admin")
    def get(self):
        ensure_survey_table()
        return jsonify([r.read() for r in ShorelineSurvey.query.order_by(ShorelineSurvey.updated_at.desc()).all()])


class AdminAnalyticsAPI(Resource):
    """Community totals for the admin Analytics tab. Admin role only."""

    @token_required("Admin")
    def get(self):
        ensure_survey_table()
        signups = ShorelineSignup.query.all()
        surveys = ShorelineSurvey.query.all()
        profiles = ShorelineProfile.query.all()
        hours = ShorelineHours.query.all()

        member_ids = {row.user_id for rows in (signups, surveys, profiles, hours) for row in rows}
        volunteer_ids = {h.user_id for h in hours}
        names = {u.id: u.name for u in User.query.filter(User.id.in_(volunteer_ids)).all()} if volunteer_ids else {}

        return jsonify(build_analytics(
            member_ids=member_ids,
            signup_dates=[s.created_at for s in signups],
            survey_choices=[s.choice for s in surveys],
            profiles=[p.read() for p in profiles],
            hours=[{"user_id": h.user_id, "activity": h.activity, "hours": h.hours} for h in hours],
            names=names,
        ))


def _clean(value, limit):
    return str(value or "").strip()[:limit]


def _profile_payload(user):
    profile = ShorelineProfile.query.filter_by(user_id=user.id).first()
    survey = ShorelineSurvey.query.filter_by(user_id=user.id).first()
    entries = ShorelineHours.query.filter_by(user_id=user.id) \
        .order_by(ShorelineHours.date.desc(), ShorelineHours.id.desc()).all()
    total = round(sum(e.hours for e in entries), 2)
    payload = {
        "uid": user.uid,
        "name": user.name,
        "email": getattr(user, "email", "") if getattr(user, "email", "") != "?" else "",
        "choice": survey.choice if survey else None,
        "hours": [e.read() for e in entries],
        "total_hours": total,
        "shifts": len(entries),
        "options": {
            "neighborhoods": NEIGHBORHOODS,
            "availability": AVAILABILITY,
            "interests": INTERESTS,
            "activities": ACTIVITIES,
        },
    }
    payload.update(profile.read() if profile else ShorelineProfile().read())
    return payload


class ProfileAPI(Resource):
    @token_required()
    def get(self):
        ensure_survey_table()
        return jsonify(_profile_payload(g.current_user))

    @token_required()
    def put(self):
        ensure_survey_table()
        user = g.current_user
        body = request.get_json(silent=True) or {}

        # Validate everything first so a bad field doesn't half-save the profile.
        name = _clean(body.get("name"), 80)
        email = _clean(body.get("email"), 120)
        if "name" in body and len(name) < 2:
            return {"message": "Name must be at least 2 characters"}, 400
        if "email" in body and email and "@" not in email:
            return {"message": "Enter a valid email"}, 400
        neighborhood = _clean(body.get("neighborhood"), 40)
        if neighborhood and neighborhood not in NEIGHBORHOODS:
            return {"message": f"neighborhood must be one of {NEIGHBORHOODS}"}, 400
        availability = _clean(body.get("availability"), 40)
        if availability and availability not in AVAILABILITY:
            return {"message": f"availability must be one of {AVAILABILITY}"}, 400
        interests = body.get("interests") or []
        if not isinstance(interests, list) or any(i not in INTERESTS for i in interests):
            return {"message": f"interests must be a list from {INTERESTS}"}, 400
        choice = _clean(body.get("choice"), 16).lower()
        if choice and choice not in VALID_CHOICES:
            return {"message": f"choice must be one of {sorted(VALID_CHOICES)}"}, 400

        user_changes = {k: v for k, v in (("name", name), ("email", email)) if k in body and v}
        if user_changes:
            user.update(user_changes)

        profile = ShorelineProfile.query.filter_by(user_id=user.id).first()
        if profile is None:
            profile = ShorelineProfile(user_id=user.id)
            db.session.add(profile)
        if "phone" in body:
            profile.phone = _clean(body.get("phone"), 30)
        if "neighborhood" in body:
            profile.neighborhood = neighborhood
        if "availability" in body:
            profile.availability = availability
        if "interests" in body:
            profile.interests = ",".join(dict.fromkeys(interests))
        if "bio" in body:
            profile.bio = _clean(body.get("bio"), 500)

        if choice:
            survey = ShorelineSurvey.query.filter_by(user_id=user.id).first()
            if survey:
                survey.choice = choice
            else:
                db.session.add(ShorelineSurvey(user_id=user.id, choice=choice))

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return {"message": "could not save profile"}, 500
        return jsonify(_profile_payload(user))


class HoursAPI(Resource):
    @token_required()
    def post(self):
        ensure_survey_table()
        body = request.get_json(silent=True) or {}
        try:
            day = date.fromisoformat(str(body.get("date", "")))
        except ValueError:
            return {"message": "date must be YYYY-MM-DD"}, 400
        if day > date.today():
            return {"message": "date can't be in the future"}, 400
        try:
            hours = round(float(body.get("hours")), 2)
        except (TypeError, ValueError):
            return {"message": "hours must be a number"}, 400
        if not 0.25 <= hours <= 24:
            return {"message": "hours must be between 0.25 and 24"}, 400
        activity = _clean(body.get("activity"), 40)
        if activity not in ACTIVITIES:
            return {"message": f"activity must be one of {ACTIVITIES}"}, 400

        entry = ShorelineHours(user_id=g.current_user.id, date=day, activity=activity,
                               hours=hours, notes=_clean(body.get("notes"), 200))
        db.session.add(entry)
        db.session.commit()
        return jsonify(_profile_payload(g.current_user))


class HoursItemAPI(Resource):
    @token_required()
    def delete(self, entry_id):
        ensure_survey_table()
        entry = ShorelineHours.query.filter_by(id=entry_id, user_id=g.current_user.id).first()
        if entry is None:
            return {"message": "entry not found"}, 404
        db.session.delete(entry)
        db.session.commit()
        return jsonify(_profile_payload(g.current_user))


class PreferencesAPI(Resource):
    """GET/PUT /api/shoreline/preferences: the signed-in user's own preferences only."""

    @token_required()
    def get(self):
        ensure_survey_table()
        row = ShorelinePreferences.query.filter_by(user_id=g.current_user.id).first()
        if row is None:
            return jsonify({"preferences": None})
        try:
            prefs = json.loads(row.data or "{}")
        except ValueError:
            # A damaged row shouldn't lock the user out of the page; the frontend uses defaults.
            app.logger.warning("Shoreline: unreadable preferences for user %s", g.current_user.id)
            prefs = None
        return jsonify({"preferences": prefs, "updated": row.updated_at.isoformat() if row.updated_at else None})

    @token_required()
    def put(self):
        ensure_survey_table()
        body = request.get_json(silent=True) or {}
        try:
            prefs = clean_preferences(body.get("preferences"))
        except PreferencesError as err:
            return {"message": str(err)}, 400
        row = ShorelinePreferences.query.filter_by(user_id=g.current_user.id).first()
        if row is None:
            row = ShorelinePreferences(user_id=g.current_user.id)
            db.session.add(row)
        row.data = json.dumps(prefs, separators=(",", ":"))
        try:
            db.session.commit()
        except IntegrityError:
            # Two tabs saved the first time at once: the other insert won, so update that row.
            db.session.rollback()
            row = ShorelinePreferences.query.filter_by(user_id=g.current_user.id).first()
            row.data = json.dumps(prefs, separators=(",", ":"))
            db.session.commit()
        return jsonify({"preferences": prefs})


class PublicStatsAPI(Resource):
    """GET /api/shoreline/stats: live site totals for anyone, no login and no personal data.

    Shaped for the OCS UI Builder's "Data from your API" block (Numbers view):
    list_path "stats", value_path "value", label_path "label". Counts only, never names."""

    def get(self):
        ensure_survey_table()
        total_hours = db.session.query(db.func.coalesce(db.func.sum(ShorelineHours.hours), 0)).scalar() or 0
        choices = dict(
            db.session.query(ShorelineSurvey.choice, db.func.count(ShorelineSurvey.id))
            .group_by(ShorelineSurvey.choice).all()
        )
        hours_text = f"{total_hours:,.0f}" if float(total_hours).is_integer() else f"{total_hours:,.1f}"
        stats = [
            {"label": "Members signed up", "value": f"{ShorelineSignup.query.count():,}"},
            {"label": "Want to volunteer", "value": f"{choices.get('volunteer', 0):,}"},
            {"label": "Want to donate", "value": f"{choices.get('donate', 0):,}"},
            {"label": "Volunteer hours logged", "value": hours_text},
            {"label": "Shifts logged", "value": f"{ShorelineHours.query.count():,}"},
        ]
        return jsonify({"updated": datetime.utcnow().isoformat(timespec="seconds") + "Z", "stats": stats})


api.add_resource(SignupAPI, "/signup")
api.add_resource(PublicStatsAPI, "/stats")
api.add_resource(SurveyAPI, "/survey")
api.add_resource(SurveyAllAPI, "/survey/all")
api.add_resource(AdminAnalyticsAPI, "/admin/analytics")
api.add_resource(ProfileAPI, "/profile")
api.add_resource(HoursAPI, "/hours")
api.add_resource(HoursItemAPI, "/hours/<int:entry_id>")
api.add_resource(PreferencesAPI, "/preferences")


def initShorelineSurveys():
    """Create the Shoreline tables (used by scripts/db_init.py via initUsers-style init).

    Not called at import: gunicorn starts several workers at once, and on a fresh database
    they would all run CREATE TABLE together and crash with "table already exists".
    The routes call ensure_survey_table() instead, which is safe under that race."""
    with app.app_context():
        ensure_survey_table()