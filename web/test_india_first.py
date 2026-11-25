"""India-first account choices precede collection and share one reader journey."""
from html.parser import HTMLParser
import html
import re
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from accounts.models import User


class Controls(HTMLParser):
    def __init__(self, content):
        super().__init__();self.controls=[];self.feed(content)
    def handle_starttag(self, tag, attrs):
        if tag in {'input','form','select','textarea'}:self.controls.append((tag,dict(attrs)))


@override_settings(INDIA_FIRST_LAUNCH_ENABLED=True,GUARDIAN_AUTHORIZATION_ENABLED=True,MAISON_ACCOUNT_MODES={"IN":"adult_only"})
class IndiaFirstScreensTests(TestCase):
    def test_initial_choice_collects_no_child_details_and_no_google_identity(self):
        for path in ['/en/sign-up/','/bn/sign-up/']:
            response=self.client.get(path,follow=True);self.assertEqual(response.status_code,200)
            source=response.content.decode();controls=Controls(source).controls
            # No separate age-choice screen: the adult-only declaration sits on the signup form.
            self.assertNotContains(response,'data-account-preflight')
            self.assertNotContains(response,'Help a younger reader')
            self.assertContains(response,'name="account_capacity" value="adult"')
            self.assertContains(response,'I am 18 or older')
            self.assertEqual(response['Content-Language'],'en')

    def test_forged_underage_post_does_not_create_or_echo_account_data(self):
        data={'account_capacity':'under18','email':'never-collected-ui@example.test','display_name':'Do not echo me','password':'Never-UI-Collected-2026'}
        response=self.client.post('/en/sign-up/',data)
        self.assertEqual(response.status_code,422)
        self.assertNotContains(response,data['email'],status_code=422)
        self.assertNotContains(response,data['display_name'],status_code=422)
        self.assertFalse(User.objects.filter(email=data['email']).exists())

    @override_settings(FEATURES={**settings.FEATURES,'google_oauth':True})
    def test_adult_password_and_google_creation_have_separate_affirmative_choices(self):
        response=self.client.get('/en/sign-up/',{'account_capacity':'adult','return_to':'/en/learn/'})
        source=response.content.decode();controls=Controls(source).controls
        choices=[attrs for tag,attrs in controls if attrs.get('name')=='account_terms_consent']
        self.assertEqual(len(choices),2)
        self.assertTrue(all('required' in item and 'checked' not in item for item in choices))
        self.assertEqual(sum(attrs.get('value')=='india-account-v1' for tag,attrs in controls),2)
        self.assertContains(response,'name="create_account" value="true"')
        self.assertContains(response,'name="account_capacity" value="adult"')
        self.assertContains(response,'Render and Neon in Singapore')
        self.assertContains(response,'consent to the necessary account and overseas processing')
        self.assertContains(response,'name="return_path" value="/en/learn/"')
        self.assertNotContains(response,'Helping someone under 18?')
        self.assertNotContains(response,'data-account-preflight')

    @override_settings(FEATURES={**settings.FEATURES,'google_oauth':True})
    def test_google_recovery_signup_preserves_safe_reader_destination_and_escapes_query(self):
        destination='/bn/learn/?track=original&topic=streams#lesson'
        expected='/en/learn/?track=original&topic=streams#lesson'
        response=self.client.get('/en/sign-in/',{'google_error':'account_registration_required','return_to':destination})
        self.assertContains(response,'No new account was created')
        match=re.search(r'New to Earnalism\? <a href="([^"]+)">Create an account</a>',response.content.decode())
        self.assertIsNotNone(match)
        signup=html.unescape(match[1]);parsed=urlsplit(signup)
        self.assertEqual(parsed.path,'/en/sign-up/')
        self.assertEqual(parse_qs(parsed.query),{'return_to':[expected]})
        self.assertNotIn('&topic=',match[1])
        self.assertIn('%26topic%3Dstreams%23lesson',match[1])
        choice=self.client.get(signup)
        self.assertContains(choice,'name="account_capacity" value="adult"')
        self.assertContains(choice,'name="return_to" value="'+html.escape(expected)+'"')
        unsafe=self.client.get('/en/sign-in/',{'google_error':'account_registration_required','return_to':'https://outside.example.test/collect'})
        link=re.search(r'New to Earnalism\? <a href="([^"]+)">Create an account</a>',unsafe.content.decode())[1]
        self.assertEqual(parse_qs(urlsplit(html.unescape(link)).query),{'return_to':['/en/']})

    def test_adult_form_submission_forwards_the_exact_account_permission(self):
        with patch('accounts.services.register_member') as register:
            response=self.client.post('/en/sign-up/',{'email':'ui-adult@example.test','display_name':'Reader','password':'Ui-Adult-Password-2026','password_purpose_consent':'on','password_purpose_version':'password-account-v1','account_capacity':'adult','account_notice_version':'india-account-v1','account_terms_consent':'on'})
        self.assertEqual(response.status_code,200)
        args=register.call_args.kwargs
        self.assertEqual(args['account_capacity'],'adult')
        self.assertEqual(args['account_notice_version'],'india-account-v1')
        self.assertIs(args['account_terms_consent'],True)
        self.assertEqual(args['locale'],'en')

    def test_parent_explanation_precedes_account_details_without_vendor_or_upload(self):
        response=self.client.get('/en/guardian/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Begin with a parent or guardian')
        self.assertContains(response,'We do not ask for a date of birth')
        self.assertContains(response,'before entering the younger reader')
        self.assertContains(response,'href="/en/sign-in/?return_to=%2Fen%2Fguardian%2F"')
        self.assertNotContains(response,'Guardian permissions are not available yet')
        self.assertNotContains(response,'KWS')
        self.assertNotContains(response,'Epic')
        self.assertNotContains(response,'type="file"')
        self.assertFalse(Controls(response.content.decode()).controls)

    def test_independent_route_uses_current_password_and_exact_adult_permission(self):
        response=self.client.get('/en/independent-account/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'name="account_notice_version" value="india-account-v1"')
        self.assertContains(response,'autocomplete="current-password"')
        self.assertContains(response,'name="account_terms_consent" required')
        self.assertContains(response,'keep the same verified account')
        with patch('accounts.enrollment.become_independent_with_password',return_value={'status':'delivery_pending'}) as update:
            result=self.client.post('/en/independent-account/',{'email':'same-reader@example.test','password':'Current-Ui-Password-47','password_purpose_consent':'on','password_purpose_version':'password-account-v1','account_capacity':'adult','account_notice_version':'india-account-v1','account_terms_consent':'on'})
        self.assertEqual(result.status_code,200)
        self.assertContains(result,'If the verified account and password matched')
        self.assertEqual(update.call_args.kwargs['email'],'same-reader@example.test')
        self.assertIs(update.call_args.kwargs['account_terms_consent'],True)

    def test_india_legal_copy_is_public_free_scope_without_worldwide_or_custody_claim(self):
        for path in ['/en/privacy/','/en/terms/','/en/contact/']:
            response=self.client.get(path);self.assertEqual(response.status_code,200)
            self.assertContains(response,'Free access · Updated 22 November 2026')
            self.assertContains(response,'drafts remain private')
            self.assertNotContains(response,'Current accounts belong to authorized adult staff/testers')
            self.assertNotContains(response,'ronik18@gmail.com')
        response=self.client.get('/en/terms/')
        self.assertContains(response,'currently available in India')
        self.assertNotContains(response,'This is the Earnalism qualification service')
        self.assertContains(self.client.get('/en/privacy/'),'Readers of every age')

    def test_foreign_service_state_has_only_help_links_no_account_collection(self):
        source=render_to_string('web/region_unavailable.html')
        self.assertFalse(Controls(source).controls)
        self.assertIn('not yet available in your country',source)
        self.assertIn('mailto:sales@reoenterprise.org',source)
        self.assertIn('href="/en/privacy/"',source)
        self.assertNotIn('/sign-up/',source)
        self.assertNotIn('<script',source)
