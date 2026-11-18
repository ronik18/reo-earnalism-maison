import re
from functools import wraps
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from django import forms
from django.conf import settings as django_settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .i18n import catalogue, text


def trusted_territory(request):
    value = getattr(request, "territory", "IN" if django_settings.LOCAL else "ZZ")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z]{2}", value) else "ZZ"


def safe_return(value, locale="en"):
    """Only local product paths, never auth loops or external/token destinations."""
    fallback = f"/{locale}/"
    if not isinstance(value, str) or len(value) > 2048 or any(c in value for c in "\r\n\\"):
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not re.match(r"^/(en|bn)/", parsed.path):
        return fallback
    if any(part in parsed.path for part in ("sign-in", "sign-up", "sign-out", "password-reset", "verify-email")):
        return fallback
    return value


def context(request, locale, **extra):
    if locale not in ("en", "bn"):
        raise Http404
    other = "bn" if locale == "en" else "en"
    switch = re.sub(r"^/(en|bn)/", f"/{other}/", request.get_full_path(), count=1)
    prefs = None
    if request.user.is_authenticated:
        try:
            prefs = request.user.preferences
        except ObjectDoesNotExist:
            pass
    return {
        "app_theme": prefs.theme if prefs and prefs.theme in ("light", "dark", "true_black") else "dark",
        "reduced_motion": bool(prefs and prefs.reduced_motion),
        "ui_locale": locale, "ui": catalogue(locale), "switch_locale_url": switch,
        "return_to": safe_return(request.POST.get("return_to", request.GET.get("return_to", request.get_full_path())), locale),
        "active_nav": "home", "focused": False, "offline_enabled":django_settings.FEATURES.get("offline_text_audio",False), "local_build":django_settings.LOCAL, "allow_index":False, **extra,
    }


def page(request, locale, template, status=200, **extra):
    response = render(request, template, context(request, locale, **extra), status=status)
    # Local first implementation. Shared caching is qualified separately by Lane D.
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response["Content-Language"] = locale
    return response


def error_page(request, locale, code="error", status=400):
    aliases = {"not_found": "not_found", "access_denied": "not_authorized", "entitlement_required": "not_authorized", "region_unavailable": "not_authorized", "invalid_token": "token_expired", "token_used": "token_expired", "action_token_invalid": "token_expired", "unverified_email": "email_unverified"}
    return page(request, locale, "web/status.html", status=status, error_key=aliases.get(code, code if code in catalogue(locale) else "error"))


def domain_view(fn):
    @wraps(fn)
    def wrapped(request, locale="en", **kwargs):
        from core.api import DomainError
        try:
            if locale not in ("en", "bn"):
                raise Http404
            return fn(request, locale=locale, **kwargs)
        except DomainError as exc:
            return error_page(request, locale, getattr(exc, "code", "error"), getattr(exc, "status", 400))
        except (ObjectDoesNotExist, ValueError):
            return error_page(request, locale, "not_found", 404)
    return wrapped


def token_response(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        response = fn(*args, **kwargs)
        response["Referrer-Policy"] = "no-referrer"
        return response
    return wrapped


def member_required(fn):
    @wraps(fn)
    def wrapped(request, locale="en", **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseRedirect(reverse("web:sign-in", args=[locale]) + "?" + urlencode({"return_to": safe_return(request.get_full_path(), locale)}))
        return fn(request, locale=locale, **kwargs)
    return wrapped


@require_GET
def root(request):
    return HttpResponseRedirect("/en/")


@require_GET
@domain_view
def home(request, locale):
    from library.services import catalog_cards
    cards = catalog_cards(locale=request.GET.get("content_locale", locale), territory=trusted_territory(request))
    return page(request, locale, "web/home.html", cards=cards, featured=cards[0] if cards else None, allow_index=not django_settings.LOCAL)


@require_GET
@domain_view
def welcome(request, locale):
    return page(request, locale, "web/welcome.html")


@require_GET
@domain_view
def search(request, locale):
    from library.services import catalog_cards
    selected = {key: request.GET.get(key, "") for key in ("q", "format", "house", "duration_min", "duration_max", "level", "topic", "access", "recency_days")}
    content_locale = request.GET.get("content_locale", locale)
    if content_locale not in ("en", "bn"):
        return error_page(request, locale, "invalid_input")
    cards = catalog_cards(locale=content_locale, territory=trusted_territory(request), query=selected["q"], house=selected["house"], format=selected["format"], **{key: selected[key] for key in ("duration_min", "duration_max", "level", "topic", "access", "recency_days")})
    return page(request, locale, "web/search.html", cards=cards, selected=selected, content_locale=content_locale, active_nav="explore")


@require_GET
@domain_view
def title(request, locale, identifier):
    from library.services import edition_detail, edition_units, get_edition_by_slug, catalog_cards
    try:
        edition_id = UUID(identifier)
    except ValueError:
        edition_id = get_edition_by_slug(identifier, locale=request.GET.get("content_locale") or None).pk
    edition = edition_detail(edition_id, territory=trusted_territory(request), user=request.user)
    units = edition_units(edition_id, territory=trusted_territory(request), user=request.user)
    other_locale = "bn" if edition["locale"] == "en" else "en"
    paired = [card for card in catalog_cards(locale=other_locale, territory=trusted_territory(request)) if card["work_id"] == edition["work_id"]]
    back_cover=None
    if not edition['published_at']:
        from library.models import Revision
        revision=Revision.objects.get(pk=edition['edition_revision_id'])
        pair=revision.validation_evidence.get('cover_pair',{})
        if pair.get('back'):back_cover='/api/v1/staff/draft-covers/'+pair['back']['asset_id']
    download_bootstrap = {"edition_revision_id":edition["edition_revision_id"],"unit_ids":[u["unit_id"] for u in units],"units":[{"unit_id":u["unit_id"],"title":u["title"]} for u in units],"formats":edition["downloadable_formats"],"title":edition["title"],"locale":edition["locale"]} if django_settings.FEATURES.get("offline_text_audio") and edition["published_at"] and request.user.is_authenticated else None
    return page(request, locale, "web/title.html", edition=edition, units=units, paired_editions=paired, back_cover=back_cover, active_nav="explore", download_bootstrap=download_bootstrap, audio_available=django_settings.FEATURES.get("audio") and "audio" in edition["formats"], allow_index=not django_settings.LOCAL and bool(edition["published_at"]))


@require_GET
@domain_view
def reader(request, locale, edition_id, unit_id=None):
    from library.services import get_reader_document, get_preview_document, edition_units
    if unit_id is None:
        units = edition_units(edition_id, territory=trusted_territory(request), user=request.user)
        if not units:
            raise Http404
        return HttpResponseRedirect(reverse("web:reader", args=[locale, edition_id, units[0]["unit_id"]]))
    document = (get_reader_document(request.user, edition_id, unit_id, territory=trusted_territory(request)) if request.user.is_authenticated else get_preview_document(edition_id, unit_id, territory=trusted_territory(request)))
    edition = document["edition"]
    try:
        offset = max(0, min(32000, int(request.GET.get("offset", "0"))))
    except (TypeError, ValueError):
        offset = 0
    bootstrap = {"edition_id": str(edition_id), "edition_revision_id": str(edition["edition_revision_id"]), "unit_id": str(unit_id), "content_locale": edition["locale"], "authenticated": request.user.is_authenticated, "anchor": request.GET.get("anchor", ""), "offset_chars": offset,"member_id":str(request.user.public_id) if request.user.is_authenticated else None,"device_id":str(request.device.id) if getattr(request,"device",None) else None}
    units=edition_units(edition_id,territory=trusted_territory(request),user=request.user)
    index=next((i for i,u in enumerate(units) if u["unit_id"]==str(unit_id)),0)
    bootstrap["previous_unit_url"]=reverse("web:reader",args=[locale,edition_id,units[index-1]["unit_id"]]) if index>0 else None
    bootstrap["next_unit_url"]=reverse("web:reader",args=[locale,edition_id,units[index+1]["unit_id"]]) if index+1<len(units) else None
    bootstrap["player_url"]=reverse("web:player",args=[locale,edition_id]) if request.user.is_authenticated and django_settings.FEATURES.get("audio") and "audio" in edition["formats"] else None
    destination = request.get_full_path()
    if document.get("preview") and document.get("boundary"):
        boundary = document["boundary"]
        destination = reverse("web:reader", args=[locale, edition_id, unit_id]) + "?" + urlencode({"anchor":boundary["end_anchor_id"],"offset":boundary["end_offset_chars"]})
    return page(request, locale, "web/reader.html", document=document, edition=edition, bootstrap=bootstrap, focused=True, active_nav="explore", return_to=destination)


class EmailForm(forms.Form):
    email = forms.EmailField(max_length=254)


class LoginForm(EmailForm):
    password = forms.CharField(strip=False)


@domain_view
def sign_in(request, locale):
    from accounts.services import login_member
    from core.api import DomainError
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            try:
                login_member(request, **form.cleaned_data)
            except DomainError as exc:
                key = {"verification_required": "email_unverified", "email_verification_required": "email_unverified"}.get(exc.code, "invalid_credentials")
                return page(request, locale, "web/auth.html", status=exc.status, auth_mode="sign-in", error_key=key, values={"email": form.cleaned_data["email"]})
            return HttpResponseRedirect(safe_return(request.POST.get("return_to"), locale))
        return page(request, locale, "web/auth.html", status=400, auth_mode="sign-in", error_key="invalid_input", values=request.POST)
    return page(request, locale, "web/auth.html", auth_mode="sign-in")


@domain_view
def sign_up(request, locale):
    from accounts.services import register_member
    from core.api import DomainError
    if request.method == "POST":
        form = LoginForm(request.POST)
        if not form.is_valid():
            return page(request, locale, "web/auth.html", status=400, auth_mode="sign-up", error_key="invalid_input", values=request.POST)
        try:
            register_member(**form.cleaned_data, display_name=request.POST.get("display_name", ""), locale=locale, return_path=safe_return(request.POST.get("return_to"), locale))
        except DomainError as exc:
            return page(request, locale, "web/auth.html", status=exc.status, auth_mode="sign-up", error_key="invalid_input", values={"email":form.cleaned_data["email"], "display_name":request.POST.get("display_name", "")})
        return page(request, locale, "web/auth.html", auth_mode="sign-up", notice_key="registration_sent")
    return page(request, locale, "web/auth.html", auth_mode="sign-up")


@domain_view
def password_reset(request, locale):
    from accounts.services import request_password_reset
    if request.method == "POST":
        form = EmailForm(request.POST)
        if not form.is_valid():
            return page(request, locale, "web/auth.html", status=400, auth_mode="reset", error_key="invalid_input", values=request.POST)
        request_password_reset(form.cleaned_data["email"], return_path=safe_return(request.POST.get("return_to"), locale))
        return page(request, locale, "web/auth.html", auth_mode="reset", notice_key="recovery_sent")
    return page(request, locale, "web/auth.html", auth_mode="reset")


@token_response
@domain_view
def password_reset_confirm(request, locale, token):
    from accounts.services import confirm_password_reset
    from core.api import DomainError
    if request.method == "POST":
        try:
            confirm_password_reset(token, request.POST.get("password", ""))
        except DomainError as exc:
            return page(request, locale, "web/auth.html", status=exc.status, auth_mode="reset-confirm", error_key="token_expired" if exc.code == "action_token_invalid" else "invalid_input")
        return page(request, locale, "web/auth.html", auth_mode="sign-in", notice_key="password_changed")
    response = page(request, locale, "web/auth.html", auth_mode="reset-confirm")
    response["Referrer-Policy"] = "no-referrer"
    return response


@token_response
@domain_view
def verify_email(request, locale, token):
    from accounts.services import confirm_email_verification
    if request.method == "POST":
        confirm_email_verification(token)
        return page(request, locale, "web/auth.html", auth_mode="sign-in", notice_key="verified")
    response = page(request, locale, "web/auth.html", auth_mode="verify")
    response["Referrer-Policy"] = "no-referrer"
    return response


def verify_landing(request):
    locale = request.GET.get("locale") or safe_return(request.GET.get("return_to")).split("/")[1]
    return verify_email(request, locale=locale, token=request.GET.get("token", ""))


def reset_landing(request):
    locale = request.GET.get("locale") or safe_return(request.GET.get("return_to")).split("/")[1]
    return password_reset_confirm(request, locale=locale, token=request.GET.get("token", ""))


@require_POST
@member_required
@domain_view
def sign_out(request, locale):
    from accounts.services import logout_member
    logout_member(request)
    return HttpResponseRedirect(reverse("web:home", args=[locale]))


@require_GET
@member_required
@domain_view
def vault(request, locale):
    return page(request, locale, "web/vault.html", active_nav="vault", vault_tab=request.GET.get("tab", "saved"))


@require_GET
@member_required
@domain_view
def personal_list(request, locale, list_id):
    from library.services import catalog_cards
    choices = catalog_cards(locale="en", territory=trusted_territory(request)) + catalog_cards(locale="bn", territory=trusted_territory(request))
    return page(request, locale, "web/list.html", active_nav="vault", list_id=str(list_id), available_editions=choices[:500])


@require_GET
@member_required
@domain_view
def downloads(request, locale):
    return page(request, locale, "web/downloads.html", active_nav="vault", download_bootstrap={})


@require_GET
@member_required
@domain_view
def settings(request, locale):
    return page(request, locale, "web/settings.html", active_nav="vault", account_bootstrap={"staff":request.user.is_staff})


@require_GET
@domain_view
def pass_page(request, locale):
    return page(request, locale, "web/pass.html")


@require_GET
@domain_view
def learn(request, locale):
    request.user.request_territory = trusted_territory(request)
    from learning.services import list_tracks
    return page(request, locale, "web/learn.html", tracks=list_tracks(request.user, locale), active_nav="learn")


@require_GET
@domain_view
def track(request, locale, track_id):
    request.user.request_territory = trusted_territory(request)
    from learning.services import track_detail, interview_questions
    data = track_detail(request.user, track_id)
    questions = interview_questions(request.user, track_id) if data.get("kind") == "sde_interview" else []
    return page(request, locale, "web/track.html", track=data, questions=questions, active_nav="learn")


@require_GET
@domain_view
def lesson(request, locale, lesson_id):
    request.user.request_territory = trusted_territory(request)
    from learning.services import lesson_detail, quiz_public
    data = lesson_detail(request.user, lesson_id)
    quiz = quiz_public(request.user, data["quiz_id"]) if data.get("quiz_id") else None
    return page(request, locale, "web/lesson.html", lesson=data, quiz=quiz, active_nav="learn")


@require_GET
@domain_view
def interview(request, locale):
    request.user.request_territory = trusted_territory(request)
    from learning.services import list_tracks
    tracks = [track for track in list_tracks(request.user, locale) if track.get("kind") == "sde_interview"]
    return page(request, locale, "web/learn.html", tracks=tracks, interview=True, active_nav="learn")


@require_GET
@domain_view
def series(request, locale):
    from library.services import catalog_cards
    return page(request, locale, "web/search.html", cards=catalog_cards(locale=locale, territory=trusted_territory(request), format="video"), selected={"format": "video"}, content_locale=locale, active_nav="series")


@require_GET
@domain_view
def question(request, locale, track_id, question_id):
    request.user.request_territory = trusted_territory(request)
    from learning.services import interview_questions, track_detail
    questions = interview_questions(request.user, track_id)
    question = next((q for q in questions if str(q["question_id"]) == str(question_id)), None)
    if question is None:
        raise Http404
    return page(request, locale, "web/question.html", question=question, track=track_detail(request.user, track_id), active_nav="learn")


@require_GET
@domain_view
def unavailable(request, locale):
    return page(request, locale, "web/status.html", status=410, error_key="not_available")


@require_GET
@member_required
@domain_view
def player(request, locale, edition_id):
    from library.services import edition_detail,media_chapters
    if not django_settings.FEATURES.get("audio"):
        return error_page(request,locale,"not_available",404)
    edition=edition_detail(edition_id,territory=trusted_territory(request),user=request.user)
    chapters=media_chapters(request.user,edition["edition_revision_id"],territory=trusted_territory(request))
    if not chapters:return error_page(request,locale,"not_available",404)
    bootstrap={"edition_id":str(edition_id),"edition_revision_id":edition["edition_revision_id"],"title":edition["title"],"locale":edition["locale"],"chapters":chapters,"reader_url":reverse("web:reader-start",args=[locale,edition_id])}
    selected=next((chapter for chapter in chapters if chapter["asset_id"]==request.GET.get("asset") or chapter["unit_id"]==request.GET.get("unit_id")),None)
    if selected:
        try:start=max(0,min(selected["duration_ms"],int(request.GET.get("position_ms","0"))))
        except (TypeError,ValueError):start=0
        bootstrap.update(start_asset_id=selected["asset_id"],start_ms=start)
    return page(request,locale,"web/player.html",edition=edition,bootstrap=bootstrap,active_nav="explore",focused=True)


@require_GET
@domain_view
def offline_shell(request,locale):
    from copy import copy
    from django.contrib.auth.models import AnonymousUser
    public_request=copy(request)
    public_request.user=AnonymousUser()
    response=page(public_request,locale,"web/offline.html",download_bootstrap={"offline":True})
    response["Cache-Control"]="public,max-age=0,must-revalidate"
    return response


@require_GET
def service_worker(request):
    import hashlib,json
    from pathlib import Path
    from django.http import HttpResponse
    root=Path(django_settings.BASE_DIR)/"static/maison"
    manifest=json.loads((root/"dist/manifest.json").read_text())
    from django.templatetags.static import static
    names=["maison/app.css","maison/app.js","maison/logo.png","maison/fonts/typography.css"]
    names += manifest["__assets"]
    names += ["maison/fonts/"+path.name for path in (root/"fonts").glob("*.woff2")]
    names += ["maison/art/"+path.name for path in (root/"art").glob("*.webp")]
    digest=hashlib.sha256(str(getattr(django_settings,"STATIC_RELEASE_ID","")).encode())
    assets=[]
    for name in sorted(set(names)):
        if not name.startswith("maison/") or ".." in name.split("/"):
            raise ValueError("Unknown public offline asset")
        raw=(Path(django_settings.BASE_DIR)/"static"/name).read_bytes()
        content_hash=hashlib.sha256(raw).hexdigest()
        digest.update(name.encode());digest.update(content_hash.encode())
        url=static(name)
        if name in {"maison/app.css","maison/app.js"}:url+="?v="+content_hash[:12]
        assets.append(url)
    assets += ["/en/offline/","/bn/offline/"]
    source=(root/"offline-worker.js").read_text()
    digest.update(json.dumps(assets).encode());digest.update(source.encode())
    version=digest.hexdigest()[:16]
    source=source.replace("__VERSION__",version).replace("__ASSETS__",json.dumps(assets)).replace("__ASSET_BASE__",json.dumps(static("")))
    response=HttpResponse(source,content_type="text/javascript")
    response["Cache-Control"]="no-cache";response["Service-Worker-Allowed"]="/"
    return response
