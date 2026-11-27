import re
from functools import wraps
import json
from copy import copy
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from django import forms
from django.conf import settings as django_settings
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponseRedirect, QueryDict
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .i18n import catalogue, text


def trusted_territory(request):
    value = getattr(request, "territory", "IN" if django_settings.LOCAL else "ZZ")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z]{2}", value) else "ZZ"


def safe_return(value, locale="en"):
    """Only local product paths, never auth loops or external/token destinations."""
    fallback = "/en/"
    if not isinstance(value, str) or len(value) > 2048 or any(c in value for c in "\r\n\\"):
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not re.match(r"^/(en|bn)/", parsed.path):
        return fallback
    if any(part in parsed.path for part in ("sign-in", "sign-up", "sign-out", "email-sign-in", "password-reset", "verify-email", "independent-account")):
        return fallback
    return re.sub(r"^/bn/", "/en/", value, count=1)


def content_languages(request):
    from library.services import published_content_languages
    return published_content_languages(trusted_territory(request))


def context(request, locale, **extra):
    if locale not in ("en", "bn"):
        raise Http404
    locale = "en"
    prefs = None
    if request.user.is_authenticated:
        try:
            prefs = request.user.preferences
        except ObjectDoesNotExist:
            pass
    return {
        "auth_bootstrap":{"mode":extra.get("auth_mode","sign-in"),"return_path":safe_return(request.POST.get("return_to",request.GET.get("return_to")),locale),"email":extra.get("values",{}).get("email","")},
        "india_first_launch": bool(getattr(django_settings, "INDIA_FIRST_LAUNCH_ENABLED", False)),
        "adult_only_signup": __import__("accounts.enrollment", fromlist=["account_mode"]).account_mode(getattr(request, "territory", None)) == "adult_only",
        "email_link_enabled": django_settings.FEATURES.get("email_link", False),
        "google_oauth_enabled": django_settings.FEATURES.get("google_oauth", False),
        "app_theme": prefs.theme if prefs and prefs.theme in ("light", "dark", "true_black") else "light",
        "reduced_motion": bool(prefs and prefs.reduced_motion),
        "ui_locale": "en", "ui": catalogue("en"),
        "content_languages": [{"code":"en","label":"English"},{"code":"bn","label":"Bengali"}],
        "return_to": safe_return(request.POST.get("return_to", request.GET.get("return_to", request.get_full_path())), locale),
        "next_page_url":None,
        "safe_request_id":str(getattr(request,"request_id","")), "retry_url":safe_return(request.get_full_path(),locale) if request.method=="GET" else "",
        "free_access":getattr(django_settings,"FREE_ACCESS_ENABLED",False),
        "free_access_available":getattr(django_settings,"FREE_ACCESS_ENABLED",False) and trusted_territory(request) in django_settings.MAISON_PUBLICATION_TERRITORIES,
        "active_nav": "home", "focused": False, "offline_enabled":django_settings.FEATURES.get("offline_text_audio",False), "local_build":django_settings.LOCAL, "allow_index":False, **extra,
    }


def page(request, locale, template, status=200, **extra):
    next_cursor=extra.get('next_cursor') or extra.get('collection',{}).get('next_cursor')
    if next_cursor:
        query=request.GET.copy();query['cursor']=next_cursor
        extra['next_page_url']=request.path+'?'+query.urlencode()
    response = render(request, template, context(request, locale, **extra), status=status)
    # Local first implementation. Shared caching is qualified separately by Lane D.
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response["Content-Language"] = "en"
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
            return fn(request, locale="en", **kwargs)
        except DomainError as exc:
            return error_page(request, locale, getattr(exc, "code", "error"), getattr(exc, "status", 400))
        except (ObjectDoesNotExist, ValueError):
            return error_page(request, locale, "not_found", 404)
    return wrapped


def token_response(fn):
    """Keep token paths out of referrers without nulling native form Origins."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        response = fn(*args, **kwargs)
        response["Referrer-Policy"] = "strict-origin"
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


CAROUSEL_TITLES = {"giant": "the selfish giant", "bicharak": "বিচারক"}


def carousel_links(cards, locale, authenticated):
    """Each carousel card opens its own book's first chapter; guests sign up on the way and return there."""
    by_title = {str(card.get("title", "")).strip().casefold(): card for card in cards}
    links = {}
    for key, title in CAROUSEL_TITLES.items():
        card = by_title.get(title)
        target = reverse("web:reader-start", args=[locale, card["edition_id"]]) if card else reverse("web:explore", args=[locale])
        links[key] = target if authenticated else reverse("web:sign-up", args=[locale]) + "?return_to=" + target
    return links


@require_GET
@domain_view
def home(request, locale):
    from library.services import catalog_cards
    from .legal import active_countries
    cards = catalog_cards(locale=request.GET.get("content_locale") or None, territory=trusted_territory(request))
    featured = cards[0] if cards else None
    sample = public_preview_data(request, featured) if featured else {}
    countries = active_countries()
    return page(request, "en", "web/home.html", cards=cards, featured=featured, reader_sample_available=bool(sample.get("units")),
                audio_sample=sample.get("audio") if django_settings.FEATURES.get("audio") else None, allow_index=not django_settings.LOCAL,
                shelf=cards[:4], carousel=carousel_links(cards, "en", request.user.is_authenticated),
                open_countries=", ".join(countries[:-1]) + (" and " + countries[-1] if len(countries) > 1 else "".join(countries)))


@require_GET
@domain_view
def welcome(request, locale):
    return page(request, locale, "web/welcome.html", onboarding_bootstrap={"return_to":safe_return(request.GET.get("return_to"),locale),"authenticated":request.user.is_authenticated})


@require_GET
@domain_view
def guardian_guidance(request, locale):
    # A preview is not permission to collect a child's or guardian's information.
    # Root separately owns regional policy/method qualification and activation.
    if not getattr(django_settings, "GUARDIAN_AUTHORIZATION_ENABLED", False):
        raise Http404
    return page(request, "en", "web/guardian.html",
                return_to=reverse("web:guardian-guidance", args=["en"]),
                guardian_journey=bool(getattr(django_settings,"GUARDIAN_AUTHORIZATION_POLICIES",{})) and request.user.is_authenticated,
                guardian_bootstrap={"india_first":bool(getattr(django_settings,"INDIA_FIRST_LAUNCH_ENABLED",False))})


@require_GET
@domain_view
def search(request, locale):
    selected = {key: request.GET.get(key, "") for key in ("q", "format", "house", "author", "duration_min", "duration_max", "level", "topic", "access", "recency_days")}
    content_locale = request.GET.get("content_locale", "")
    from library.views import catalog, collections as collection_index
    api_path = "/api/v1/catalog" if request.path.endswith("/explore/") else "/api/v1/search"
    data = catalog_payload(request, content_locale, catalog, api_path=api_path)
    # Catalog and collection cursors have separate scopes. A result-page cursor
    # must never be sent to the independently rendered collection sidebar.
    shelf_request = copy(request)
    shelf_request.GET = request.GET.copy()
    shelf_request.GET.pop("cursor", None)
    shelf_request.GET.pop("limit", None)
    shelves = catalog_payload(shelf_request, content_locale, collection_index)["items"]
    return page(request, locale, "web/search.html", collections=shelves, cards=data["items"], next_cursor=data["next_cursor"], selected=selected, content_locale=content_locale, content_languages=content_languages(request), active_nav="explore")


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
    from library.services import authorize_revision
    from core.api import DomainError
    reader_access=False
    if request.user.is_authenticated and "reader" in edition["formats"]:
        try:
            authorize_revision(request.user,edition["edition_revision_id"],territory=trusted_territory(request))
            reader_access=True
        except DomainError:
            pass
    other_locale = "bn" if edition["locale"] == "en" else "en"
    paired = [card for card in catalog_cards(locale=other_locale, territory=trusted_territory(request)) if card["work_id"] == edition["work_id"]]
    back_cover=None
    if not edition['published_at']:
        from library.models import Revision
        revision=Revision.objects.get(pk=edition['edition_revision_id'])
        pair=revision.validation_evidence.get('cover_pair',{})
        if pair.get('back'):back_cover='/api/v1/staff/draft-covers/'+pair['back']['asset_id']
    download_bootstrap = {"edition_revision_id":edition["edition_revision_id"],"unit_ids":[u["unit_id"] for u in units],"units":[{"unit_id":u["unit_id"],"title":u["title"]} for u in units],"formats":edition["downloadable_formats"],"title":edition["title"],"locale":edition["locale"]} if django_settings.FEATURES.get("offline_text_audio") and edition["published_at"] and request.user.is_authenticated else None
    sample = public_preview_data(request, edition) if django_settings.FEATURES.get("audio") else {}
    return page(request, locale, "web/title.html", edition=edition, units=units, reader_access=reader_access, reader_action_available=reader_access or edition["preview_available"], paired_editions=paired, back_cover=back_cover, active_nav="explore", download_bootstrap=download_bootstrap, audio_available=django_settings.FEATURES.get("audio") and "audio" in edition["formats"], video_available=django_settings.FEATURES.get("video") and "video" in edition["formats"], audio_sample=sample.get("audio"), allow_index=not django_settings.LOCAL and bool(edition["published_at"]))


@require_GET
@domain_view
def reader(request, locale, edition_id, unit_id=None):
    from library.services import get_reader_document, get_preview_document, edition_units
    if unit_id is None:
        units = edition_units(edition_id, territory=trusted_territory(request), user=request.user)
        if not units:
            raise Http404
        return HttpResponseRedirect(reverse("web:reader", args=[locale, edition_id, units[0]["unit_id"]]))
    from core.api import DomainError
    try:
        document = (get_reader_document(request.user, edition_id, unit_id, territory=trusted_territory(request)) if request.user.is_authenticated else get_preview_document(edition_id, unit_id, territory=trusted_territory(request)))
    except DomainError as exc:
        if exc.code not in {"entitlement_required","access_denied"}:
            raise
        document = get_preview_document(edition_id, unit_id, territory=trusted_territory(request))
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
    bootstrap.update(free_access=getattr(django_settings,"FREE_ACCESS_ENABLED",False),preview=bool(document.get("preview")),title_url=reverse("web:title",args=[locale,edition_id]),sign_in_url=reverse("web:sign-in",args=[locale])+"?"+urlencode({"return_to":destination}),pass_url=reverse("web:pass",args=[locale])+"?"+urlencode({"return_to":destination}))
    if document.get("preview"):
        bootstrap["next_unit_url"]=None
        bootstrap["player_url"]=None
    saved_theme = None
    if request.user.is_authenticated:
        try:
            saved_theme = request.user.preferences.reader_theme
            if saved_theme == "system":
                saved_theme = None
        except ObjectDoesNotExist:
            pass
    return page(request, locale, "web/reader.html", document=document, edition=edition, bootstrap=bootstrap, focused=True, active_nav="explore", return_to=destination, reader_theme=saved_theme)


class EmailForm(forms.Form):
    email = forms.EmailField(max_length=254)


class LoginForm(EmailForm):
    password = forms.CharField(strip=False)
    password_purpose_consent = forms.BooleanField(required=True)
    password_purpose_version = forms.ChoiceField(choices=[("password-account-v1", "password-account-v1")])


@domain_view
def sign_in(request, locale):
    from accounts.services import login_member
    from core.api import DomainError
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            try:
                from accounts.password_consent import validate_password_purpose_consent
                credentials = dict(form.cleaned_data)
                consent = validate_password_purpose_consent(credentials)
                credentials.pop("password_purpose_consent")
                credentials.pop("password_purpose_version")
                login_member(request, **credentials, password_consent=consent)
            except DomainError as exc:
                key = {"verification_required": "email_unverified", "email_verification_required": "email_unverified", "rate_limited": "sign_in_rate_limited"}.get(exc.code, "invalid_credentials")
                return page(request, locale, "web/auth.html", status=exc.status, auth_mode="sign-in", error_key=key, values={"email": form.cleaned_data["email"]})
            return HttpResponseRedirect(safe_return(request.POST.get("return_to"), locale))
        return page(request, locale, "web/auth.html", status=400, auth_mode="sign-in", error_key="invalid_input", values=request.POST)
    google_errors = {
        'identity_link_required': 'google_link_required',
        'identity_already_linked': 'google_already_linked',
        'reauthentication_required': 'google_reauth_required',
        'authentication_required': 'google_signin_required',
        'email_verification_required': 'email_unverified',
        'identity_mismatch': 'google_identity_mismatch',
        'account_unavailable': 'google_account_unavailable',
        'feature_disabled': 'google_unavailable',
        'provider_not_configured': 'google_unavailable',
        'google_provider_unavailable': 'google_unavailable',
        'google_authentication_failed': 'google_retry',
        'invalid_oauth_state': 'google_retry',
        'account_registration_required': 'account_registration_required',
        'account_permission_required': 'account_permission_required',
        'adult_declaration_required': 'adult_declaration_required',
    }
    return page(request, locale, "web/auth.html", auth_mode="sign-in", error_key=google_errors.get(request.GET.get('google_error')))


@domain_view
def sign_up(request, locale):
    from accounts.services import register_member
    from core.api import DomainError
    from accounts.enrollment import account_mode
    india_first = bool(getattr(django_settings, "INDIA_FIRST_LAUNCH_ENABLED", False))
    mode = account_mode(getattr(request, "territory", None))
    if india_first and mode == "adult_only" and request.method == "POST" and request.POST.get("account_capacity") != "adult":
        # Refuse before reading or echoing any account details.
        return page(request, locale, "web/auth.html", status=422, auth_mode="sign-up", error_key="adult_declaration_required")
    if request.method == "POST":
        form = LoginForm(request.POST)
        if not form.is_valid():
            return page(request, locale, "web/auth.html", status=400, auth_mode="sign-up", error_key="invalid_input", values=request.POST)
        try:
            from accounts.password_consent import validate_password_purpose_consent
            credentials = dict(form.cleaned_data)
            consent = validate_password_purpose_consent(credentials)
            credentials.pop("password_purpose_consent")
            credentials.pop("password_purpose_version")
            register_member(**credentials, password_consent=consent, display_name=request.POST.get("display_name", ""), locale=locale, return_path=safe_return(request.POST.get("return_to"), locale), **({
                "account_capacity": request.POST.get("account_capacity"),
                "account_notice_version": request.POST.get("account_notice_version"),
                "account_terms_consent": request.POST.get("account_terms_consent") == "on",
            } if india_first else {}), territory=getattr(request, "territory", None))
        except DomainError as exc:
            return page(request, locale, "web/auth.html", status=exc.status, auth_mode="sign-up", error_key=exc.code if exc.code in ("account_permission_required", "adult_declaration_required") else "invalid_input", values={"email":form.cleaned_data["email"], "display_name":request.POST.get("display_name", "")})
        return page(request, locale, "web/auth.html", auth_mode="sign-up", notice_key="registration_sent")
    return page(request, locale, "web/auth.html", auth_mode="sign-up")


@require_http_methods(["GET", "POST"])
@domain_view
def independent_account(request, locale):
    if not getattr(django_settings, "INDIA_FIRST_LAUNCH_ENABLED", False):
        raise Http404
    if request.method == "POST":
        from accounts.enrollment import become_independent_with_password
        from accounts.password_consent import validate_password_purpose_consent
        from core.api import DomainError
        form = LoginForm(request.POST)
        if form.is_valid():
            try:
                consent = validate_password_purpose_consent(dict(form.cleaned_data))
                become_independent_with_password(request, email=form.cleaned_data["email"], password=form.cleaned_data["password"], password_consent=consent,
                    account_capacity=request.POST.get("account_capacity"), account_notice_version=request.POST.get("account_notice_version"), account_terms_consent=request.POST.get("account_terms_consent") == "on")
                return page(request, locale, "web/auth.html", auth_mode="independent", notice_key="independent_account_updated")
            except DomainError as exc:
                return page(request, locale, "web/auth.html", status=exc.status, auth_mode="independent", error_key="independent_account_unavailable")
        return page(request, locale, "web/auth.html", status=400, auth_mode="independent", error_key="invalid_input")
    return page(request, locale, "web/auth.html", auth_mode="independent")


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


@require_http_methods(["GET", "POST"])
@domain_view
def email_link(request, locale):
    from accounts.services import request_magic_signin
    from core.api import DomainError
    if not django_settings.FEATURES.get("email_link"):
        raise DomainError("feature_disabled", "Email sign-in is unavailable.", 409)
    if request.method == "POST":
        form = EmailForm(request.POST)
        if not form.is_valid():
            return page(request, locale, "web/auth.html", status=400, auth_mode="email-link", error_key="invalid_input", values=request.POST)
        request_magic_signin(form.cleaned_data["email"], locale=locale, return_path=safe_return(request.POST.get("return_to"), locale))
        return page(request, locale, "web/auth.html", auth_mode="email-link", notice_key="email_link_sent")
    return page(request, locale, "web/auth.html", auth_mode="email-link")


@token_response
@domain_view
def password_reset_confirm(request, locale, token):
    from accounts.services import confirm_password_reset
    from core.api import DomainError
    if request.method == "POST":
        try:
            from accounts.password_consent import validate_password_purpose_consent
            consent = validate_password_purpose_consent({"password_purpose_consent": request.POST.get("password_purpose_consent") == "on", "password_purpose_version": request.POST.get("password_purpose_version")})
            confirm_password_reset(token, request.POST.get("password", ""), password_consent=consent)
        except DomainError as exc:
            return page(request, locale, "web/auth.html", status=exc.status, auth_mode="reset-confirm", error_key="token_expired" if exc.code == "action_token_invalid" else "invalid_input")
        return page(request, locale, "web/auth.html", auth_mode="sign-in", notice_key="password_changed")
    return page(request, locale, "web/auth.html", auth_mode="reset-confirm")


@token_response
@domain_view
def verify_email(request, locale, token):
    from accounts.services import confirm_email_verification
    if request.method == "POST":
        confirm_email_verification(token, request=request)
        return page(request, locale, "web/auth.html", auth_mode="sign-in", notice_key="verified")
    return page(request, locale, "web/auth.html", auth_mode="verify")


def verify_landing(request):
    locale = request.GET.get("locale") or safe_return(request.GET.get("return_to")).split("/")[1]
    return verify_email(request, locale=locale, token=request.GET.get("token", ""))


def reset_landing(request):
    locale = request.GET.get("locale") or safe_return(request.GET.get("return_to")).split("/")[1]
    return password_reset_confirm(request, locale=locale, token=request.GET.get("token", ""))


@require_http_methods(["GET", "POST"])
def email_link_landing(request):
    locale = request.GET.get("locale") or safe_return(request.GET.get("return_to")).split("/")[1]
    return email_link_confirm(request, locale=locale, token=request.GET.get("token", ""))


@token_response
@domain_view
def email_link_confirm(request, locale, token):
    from core.api import DomainError
    if not django_settings.FEATURES.get("email_link"):
        raise DomainError("feature_disabled", "Email sign-in is unavailable.", 409)
    if request.method == "POST":
        from accounts.services import confirm_magic_signin
        try:
            destination = confirm_magic_signin(request, token)
        except DomainError as exc:
            return page(request, locale, "web/auth.html", status=exc.status, auth_mode="email-link-confirm", error_key="token_expired" if exc.code == "action_token_invalid" else "error")
        return HttpResponseRedirect(safe_return(destination, locale))
    return page(request, locale, "web/auth.html", auth_mode="email-link-confirm")


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
    from datetime import timedelta
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from allauth.socialaccount.models import SocialAccount
    google_enabled = django_settings.FEATURES.get('google_oauth', False)
    try:
        stamp = parse_datetime(request.session.get('reauthenticated_at', ''))
    except (TypeError, ValueError):
        stamp = None
    fresh_until = (stamp + timedelta(minutes=5)).timestamp() * 1000 if stamp and timezone.is_aware(stamp) and timedelta(0) <= timezone.now() - stamp <= timedelta(minutes=5) else 0
    return page(request, locale, "web/settings.html", active_nav="vault", support_configured=bool(django_settings.SUPPORT_EMAIL), account_bootstrap={
        "staff": request.user.is_staff, "google_enabled": google_enabled,
        "google_linked": google_enabled and SocialAccount.objects.filter(user=request.user, provider='google').exists(),
        "fresh_until": fresh_until,
    })


@require_GET
@domain_view
def pass_page(request, locale):
    destination = safe_return(request.GET.get("return_to"),locale) if request.GET.get("return_to") else reverse("web:explore",args=[locale])
    return page(request, locale, "web/pass.html", active_nav="pass", free_return_path=destination, commerce_bootstrap={"return_path":safe_return(request.GET.get("return_to"),locale)})


@require_GET
@domain_view
def learn(request, locale):
    request.user.request_territory = trusted_territory(request)
    from learning.services import tracks_page
    result=tracks_page(request,request.user,request.GET.get("content_locale") or None)
    return page(request, locale, "web/learn.html", tracks=result["items"], next_cursor=result["next_cursor"], active_nav="learn")


@require_GET
@domain_view
def track(request, locale, track_id):
    request.user.request_territory = trusted_territory(request)
    from learning.services import track_detail, interview_questions_page
    data = track_detail(request.user, track_id)
    result = interview_questions_page(request,request.user,track_id) if data.get("kind") == "sde_interview" and data.get("access") != "locked" else {"items":[],"next_cursor":None}
    return page(request, locale, "web/track.html", track=data, questions=result["items"], next_cursor=result["next_cursor"], active_nav="learn")


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
    from learning.services import tracks_page
    result = tracks_page(request,request.user,request.GET.get("content_locale") or None,kind="sde_interview")
    return page(request, locale, "web/learn.html", tracks=result["items"], next_cursor=result["next_cursor"], interview=True, active_nav="learn")


def catalog_payload(request, locale, endpoint, api_path=None, **kwargs):
    """Reuse the existing public catalog boundary without a loopback HTTP request."""
    from core.api import DomainError
    catalog_request=copy(request)
    catalog_request.GET=request.GET.copy()
    if locale:catalog_request.GET["locale"]=locale
    else:catalog_request.GET.pop("locale",None)
    catalog_request.GET["territory"]=trusted_territory(request)
    if api_path:
        catalog_request.path = catalog_request.path_info = api_path
    response=endpoint(catalog_request,**kwargs)
    data=json.loads(response.content)
    if response.status_code>=400:
        raise DomainError(data.get("code","not_found"),"Catalog destination unavailable.",response.status_code)
    return data


def public_preview_data(request, edition, *, required=False):
    """Reuse the public boundary; never infer a sample from a full audio asset."""
    from core.api import DomainError
    from library.services import edition_detail
    from library.views import preview
    try:
        if "edition_revision_id" not in edition:
            edition = edition_detail(edition["edition_id"], territory=trusted_territory(request), user=request.user)
        if not edition.get("published_at"):
            raise DomainError("preview_unavailable", "This preview is unavailable.", 404)
        sample_request = copy(request)
        sample_request.GET = QueryDict("", mutable=True)
        revision = edition["edition_revision_id"]
        return catalog_payload(sample_request, edition["locale"], preview, api_path=f"/api/v1/content/previews/{revision}", revision_id=revision)
    except DomainError:
        if required:
            raise
        return {}


@require_GET
@domain_view
def collection(request, locale, collection_id):
    from library.views import collection as endpoint
    data=catalog_payload(request,request.GET.get("content_locale"),endpoint,collection_id=collection_id)
    return page(request,locale,"web/collection.html",collection=data,cards=data["items"],content_locale=request.GET.get("content_locale", ""),active_nav="explore")


@require_GET
@domain_view
def series(request, locale, slug=None):
    from library.views import collections as index, collection as detail
    if slug:
        from library.collections import collection_detail,series_member_state,get_collection,canonical_series_slug
        from urllib.parse import urlencode
        collection=get_collection(slug,series_only=True)
        if slug!=collection.slug:
            destination=reverse("web:series-detail",args=[locale,collection.slug])
            if request.GET:destination+="?"+request.GET.urlencode()
            return HttpResponseRedirect(destination)
        data=collection_detail(request,slug,request.GET.get("content_locale") or None,trusted_territory(request),series_only=True)
        if data.get("kind")!="series":
            raise Http404
        state=series_member_state(request.user,collection,request.GET.get("content_locale") or None,trusted_territory(request),cards=data["items"])
        states={}
        for item in (state or {}).get('items',[]):
            item['resume_url']=None
            for progress in item['progress']:
                loc=progress.get('location') or {}
                if not loc.get('unit_id'):continue
                if progress['format']=='reader':
                    item['resume_url']=reverse('web:reader',args=[locale,item['edition_id'],loc['unit_id']])+'?'+urlencode({'anchor':loc.get('anchor_id',''),'offset':loc.get('offset_chars',0)})
                elif progress['format']=='audio' and django_settings.FEATURES.get('audio'):
                    item['resume_url']=reverse('web:player',args=[locale,item['edition_id']])+'?'+urlencode({'unit_id':loc['unit_id'],'position_ms':loc.get('position_ms',0)})
                if item['resume_url']:break
            states[item['edition_id']]=item
        return page(request,locale,"web/series.html",collection=data,cards=data["items"],series_progress=states,content_locale=request.GET.get("content_locale", ""),active_nav="series")
    from library.collections import list_collections
    data=list_collections(request,request.GET.get("content_locale") or None,trusted_territory(request),kind="series")
    return page(request,locale,"web/series.html",collections=[item for item in data["items"] if item.get("kind")=="series"],next_cursor=data["next_cursor"],active_nav="series")


@require_GET
@domain_view
def video(request,locale,edition_id):
    from library.services import edition_detail
    edition=edition_detail(edition_id,territory=trusted_territory(request),user=request.user)
    boot={"edition_id":str(edition_id),"edition_revision_id":edition["edition_revision_id"],"title":edition["title"],"locale":edition["locale"],"enabled":False,"title_url":reverse("web:title",args=[locale,edition_id]),"authenticated":request.user.is_authenticated}
    next_cursor = None
    if django_settings.FEATURES.get("video") and "video" in edition["formats"]:
        if not request.user.is_authenticated:
            boot["sign_in_url"] = reverse("web:sign-in", args=[locale]) + "?" + urlencode({"return_to": request.get_full_path()})
        else:
            from core.api import DomainError
            from library.models import Asset
            from library.services import authorize_revision
            from library.stream import customer_host
            from django.db.models import F
            from core.pagination import paginate_queryset
            from reader.models import Progress
            try:
                revision = authorize_revision(request.user, edition["edition_revision_id"], "video", territory=trusted_territory(request))
                from library.services import video_provider
                provider = video_provider()
                rows = Asset.objects.filter(revision=revision, kind="video", provider=provider, state="ready", unit__isnull=False, duration_ms__gt=0).select_related("unit").annotate(video_ordinal=F("unit__ordinal"))
                if provider == "stream":
                    rows = rows.filter(duration_ms=F("unit__duration_ms"))
                selected = None
                if request.GET.get("asset"):
                    selected = rows.filter(pk=UUID(request.GET["asset"])).first()
                elif request.GET.get("unit_id"):
                    selected = rows.filter(unit_id=UUID(request.GET["unit_id"])).order_by("id").first()
                else:
                    saved = Progress.objects.filter(user=request.user, edition_id=edition_id, revision=revision, format="video").values_list("location", flat=True).first()
                    if isinstance(saved, dict) and saved.get("unit_id"):
                        selected = rows.filter(unit_id=saved["unit_id"]).order_by("id").first()
                chapter_page = paginate_queryset(request, rows, "video-chapters:"+str(revision.id), ordering="video_ordinal", maximum=100)
                assets = chapter_page["items"]
                if selected is not None and all(asset.id != selected.id for asset in assets):
                    assets = [selected, *assets]
                captioned = set(Asset.objects.filter(revision=revision, kind="video_captions", state="ready", unit_id__in=[asset.unit_id for asset in assets]).values_list("unit_id", flat=True))
                chapters = [{"asset_id":str(asset.id), "unit_id":str(asset.unit_id), "duration_ms":asset.duration_ms, "title":asset.unit.title, "provider":asset.provider,
                             "sha256":asset.sha256 if asset.provider == "r2" else None,
                             "captions_url":f"/api/v1/content/video-captions/{asset.id}" if asset.provider == "r2" and asset.unit_id in captioned else None} for asset in assets]
                next_cursor = chapter_page["next_cursor"]
                if chapters:
                    boot.update(enabled=True, chapters=chapters, asset_id=chapters[0]["asset_id"], unit_id=chapters[0]["unit_id"], duration_ms=chapters[0]["duration_ms"])
                    if provider == "stream":
                        boot["stream_customer_host"] = customer_host()
                    if selected:
                        boot["start_asset_id"] = str(selected.id)
            except DomainError as exc:
                if exc.code not in {"entitlement_required", "access_denied", "email_verification_required"}:
                    raise
    if "reader" in edition["formats"]:
        boot["reader_url"]=reverse("web:reader-start",args=[locale,edition_id])
    if django_settings.FEATURES.get("audio") and "audio" in edition["formats"]:
        boot["player_url"]=reverse("web:player",args=[locale,edition_id])
    return page(request,locale,"web/video.html",edition=edition,bootstrap=boot,next_cursor=next_cursor,focused=True,active_nav="series")


@require_GET
@member_required
@domain_view
def checkout(request,locale,order_id):
    from billing.models import Order
    order=Order.objects.filter(pk=order_id,user=request.user).first()
    if not order:
        raise Http404
    return page(request,locale,"web/checkout.html",active_nav="pass",commerce_bootstrap={"order_id":str(order_id),"return_path":safe_return(order.return_path,locale),"free_access":getattr(django_settings,"FREE_ACCESS_ENABLED",False)})


@require_GET
@domain_view
def system_state(request,locale,state):
    states={"404":("not_found",404),"maintenance":("maintenance",503),"error":("error",503)}
    if state not in states:
        raise Http404
    key,status=states[state]
    return error_page(request,locale,key,status)


@require_GET
@domain_view
def question(request, locale, track_id, question_id):
    request.user.request_territory = trusted_territory(request)
    from learning.services import interview_question, track_detail
    question = interview_question(request.user, track_id, question_id)
    return page(request, locale, "web/question.html", question=question, track=track_detail(request.user, track_id), active_nav="learn")


@require_GET
@domain_view
def unavailable(request, locale):
    return page(request, locale, "web/status.html", status=410, error_key="not_available")


@require_GET
@domain_view
def audio_preview(request, locale, edition_id):
    from core.api import DomainError
    from library.services import edition_detail
    if not django_settings.FEATURES.get("audio"):
        raise DomainError("preview_unavailable", "This preview is unavailable.", 404)
    edition = edition_detail(edition_id, territory=trusted_territory(request), user=request.user)
    sample = public_preview_data(request, edition, required=True)
    clip = sample.get("audio")
    if not clip or not clip.get("unit_id"):
        raise DomainError("preview_unavailable", "This preview is unavailable.", 404)
    full_player_url = reverse("web:player", args=[locale, edition_id]) + "?" + urlencode({"unit_id": clip["unit_id"]})
    bootstrap = {"edition_id": str(edition_id), "edition_revision_id": edition["edition_revision_id"],
                 "title": edition["title"], "locale": edition["locale"], "preview": clip,
                 "chapters": [{key: clip[key] for key in ("asset_id", "unit_id", "duration_ms", "sha256", "quality_kbps")} | {"title": text("listen_sample", locale)}],
                 "reader_url": reverse("web:reader-start", args=[locale, edition_id]), "reader_available": False,
                 "authenticated": request.user.is_authenticated, "free_access":getattr(django_settings,"FREE_ACCESS_ENABLED",False), "full_player_url": full_player_url,
                 "title_url": reverse("web:title", args=[locale, edition_id]),
                 "sign_in_url": reverse("web:sign-in", args=[locale]) + "?" + urlencode({"return_to": full_player_url}),
                 "pass_url": reverse("web:pass", args=[locale]) + "?" + urlencode({"return_to": full_player_url})}
    return page(request, locale, "web/player.html", edition=edition, bootstrap=bootstrap, active_nav="explore", focused=True)


@require_GET
@member_required
@domain_view
def player(request, locale, edition_id, unit_id=None):
    from library.services import edition_detail,media_chapters
    if not django_settings.FEATURES.get("audio"):
        return error_page(request,locale,"not_available",404)
    edition=edition_detail(edition_id,territory=trusted_territory(request),user=request.user)
    chapters=media_chapters(request.user,edition["edition_revision_id"],territory=trusted_territory(request))
    if not chapters:return error_page(request,locale,"not_available",404)
    bootstrap={"edition_id":str(edition_id),"edition_revision_id":edition["edition_revision_id"],"title":edition["title"],"locale":edition["locale"],"chapters":chapters,"reader_url":reverse("web:reader-start",args=[locale,edition_id])}
    if edition.get("cover"):bootstrap.update(cover_url=edition["cover"]["url"],cover_width=edition["cover"]["width"],cover_height=edition["cover"]["height"])
    from library.services import catalog_card
    creators=catalog_card(edition_id,territory=trusted_territory(request),user=request.user).get("creators") or []
    if creators:bootstrap["author"]=", ".join(creators)
    selected=next((chapter for chapter in chapters if chapter["asset_id"]==request.GET.get("asset") or chapter["unit_id"]==str(unit_id or request.GET.get("unit_id"))),None)
    if selected:
        try:start=max(0,min(selected["duration_ms"],int(request.GET.get("position_ms","0"))))
        except (TypeError,ValueError):start=0
        bootstrap.update(start_asset_id=selected["asset_id"],start_ms=start)
    bootstrap.update(reader_available="reader" in edition["formats"],authenticated=True,title_url=reverse("web:title",args=[locale,edition_id]),sign_in_url=reverse("web:sign-in",args=[locale])+"?"+urlencode({"return_to":request.get_full_path()}),pass_url=reverse("web:pass",args=[locale]))
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
    theme=root/"peacock"
    if theme.is_dir():
        names += ["maison/peacock/"+path.relative_to(theme).as_posix() for path in theme.rglob("*.svg")]
        names += ["maison/peacock/tokens.css","maison/peacock/maison-theme.css"]
    names += ["maison/fonts/"+path.name for path in (root/"fonts").glob("*.woff2")]
    names += ["maison/art/"+path.name for path in (root/"art").iterdir() if path.suffix in {".webp",".jpg"}]
    digest=hashlib.sha256(str(getattr(django_settings,"STATIC_RELEASE_ID","")).encode())
    assets=[]
    for name in sorted(set(names)):
        if not name.startswith("maison/") or ".." in name.split("/"):
            raise ValueError("Unknown public offline asset")
        raw=(Path(django_settings.BASE_DIR)/"static"/name).read_bytes()
        content_hash=hashlib.sha256(raw).hexdigest()
        digest.update(name.encode());digest.update(content_hash.encode())
        url=static(name)
        if name in {"maison/app.css","maison/app.js","maison/peacock/maison-theme.css"}:url+="?v="+content_hash[:12]
        assets.append(url)
    assets += ["/en/offline/"]
    source=(root/"offline-worker.js").read_text()
    digest.update(json.dumps(assets).encode());digest.update(source.encode())
    version=digest.hexdigest()[:16]
    source=source.replace("__VERSION__",version).replace("__ASSETS__",json.dumps(assets)).replace("__ASSET_BASE__",json.dumps(static("")))
    response=HttpResponse(source,content_type="text/javascript")
    response["Cache-Control"]="no-cache";response["Service-Worker-Allowed"]="/"
    return response


def error_locale(request):
    return "bn" if request.path.startswith("/bn/") else "en"


def not_found(request, exception=None):
    return error_page(request,error_locale(request),"not_found",404)


def permission_denied(request, exception=None):
    return error_page(request,error_locale(request),"not_authorized",403)


def server_error(request):
    # Error rendering must survive a failed database or lazy session lookup.
    from django.contrib.auth.models import AnonymousUser
    safe_request=copy(request)
    safe_request.user=AnonymousUser()
    safe_request.session={}
    safe_request._messages=[]
    return error_page(safe_request,error_locale(request),"error",500)
