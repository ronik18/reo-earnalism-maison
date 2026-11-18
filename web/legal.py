"""Reviewable operating notices; qualification drafts are not legal clearance."""
from django.views.decorators.http import require_GET
from django.conf import settings
from .views import page

OPERATOR_ADDRESS = "Reo Enterprise, 73, Nandan Nagar, Belghoria, District - North 24 Parganas, Kolkata - 700083, India."
GRIEVANCE_ROLE = "Chief of Operations / Grievance Officer"

COPY = {
 'draft': ('Qualification draft · Updated 18 November 2026', 'যোগ্যতা যাচাইয়ের খসড়া · হালনাগাদ ১৮ নভেম্বর ২০২৬'),
 'review': ('These notices describe the current Maison qualification service. Retention, age-appropriate account safeguards and applicable regional requirements remain under review; this is not a declaration of launch or worldwide legal clearance.', 'এই বিজ্ঞপ্তি মেজঁর বর্তমান যাচাই পরিষেবার বিবরণ। তথ্য সংরক্ষণের সময়সূচি, বয়স অনুযায়ী অ্যাকাউন্টের সুরক্ষা ও প্রযোজ্য আঞ্চলিক বিষয় পর্যালোচনাধীন; এটি উদ্বোধন বা বিশ্বব্যাপী আইনি ছাড়পত্রের ঘোষণা নয়।'),
 'privacy_title': ('Privacy notice', 'গোপনীয়তার বিজ্ঞপ্তি'),
 'terms_title': ('Service terms', 'পরিষেবার শর্ত'),
 'contact_title': ('Contact Earnalism', 'আর্নালিজমের সঙ্গে যোগাযোগ'),
}
PRIVACY = [
 ('Operator and contact', 'পরিচালক ও যোগাযোগ', 'Earnalism Maison is operated by Reo Enterprise, India. For account, privacy or content questions, contact sales@reoenterprise.org. Correspondence: Reo Enterprise, 73, Nandan Nagar, Belghoria, District - North 24 Parganas, Kolkata - 700083, India. Privacy/grievance contact: Chief of Operations / Grievance Officer, at the same mailbox.', 'আর্নালিজম মেজঁ পরিচালনা করে Reo Enterprise, India। অ্যাকাউন্ট, গোপনীয়তা বা বিষয়বস্তু সম্পর্কে sales@reoenterprise.org-এ লিখুন। ডাকযোগাযোগ: Reo Enterprise, 73, Nandan Nagar, Belghoria, District - North 24 Parganas, Kolkata - 700083, India। গোপনীয়তা ও অভিযোগের জন্য একই ইমেলে Chief of Operations / Grievance Officer-কে লিখুন।'),
 ('Information and purposes', 'তথ্য ও ব্যবহার', 'Account email, profile and password hashes support sign-in and security. Reading progress, saved items, notes and preferences support requested reading features. Essential session/CSRF cookies protect access; support messages and limited security/operation records support requests and service reliability. Optional analytics and marketing require their separate preferences; no advertising or marketing consent is implied by an account.', 'ইমেল, প্রোফাইল ও পাসওয়ার্ডের হ্যাশ লগইন ও নিরাপত্তার কাজে ব্যবহৃত হয়। পড়ার অগ্রগতি, সংরক্ষিত বই, নোট ও পছন্দ পড়ার সুবিধা দেয়। প্রয়োজনীয় সেশন/CSRF কুকি প্রবেশ সুরক্ষিত রাখে; সহায়তার বার্তা ও সীমিত নিরাপত্তা/পরিচালনার তথ্য অনুরোধ ও পরিষেবার নির্ভরযোগ্যতায় সাহায্য করে। ঐচ্ছিক বিশ্লেষণ ও বিপণনের পছন্দ আলাদা; অ্যাকাউন্ট খোলা তার সম্মতি নয়।'),
 ('Service providers', 'পরিষেবা প্রদানকারী', 'The qualification uses Render for application hosting, Neon PostgreSQL for data, Cloudflare CDN/R2 for delivery/storage and Google Workspace for requested account emails. The application/database are configured in Singapore; edge delivery can occur internationally. Provider processing and applicable transfer arrangements must be finalized before public launch; we do not claim all data stays in India.', 'যাচাই পরিষেবায় অ্যাপ চালাতে Render, তথ্য রাখতে Neon PostgreSQL, সরবরাহ/স্টোরেজে Cloudflare CDN/R2 এবং অনুরোধ করা অ্যাকাউন্ট ইমেলের জন্য Google Workspace ব্যবহৃত হয়। অ্যাপ/ডেটাবেস সিঙ্গাপুরে; এজ সরবরাহ আন্তর্জাতিক হতে পারে। প্রকাশ্য উদ্বোধনের আগে প্রযোজ্য তথ্য প্রক্রিয়াকরণ ও স্থানান্তরের ব্যবস্থা চূড়ান্ত করতে হবে; সমস্ত তথ্য ভারতে থাকে বলে দাবি করা হচ্ছে না।'),
 ('Your controls and retention', 'আপনার নিয়ন্ত্রণ ও তথ্য সংরক্ষণ', 'Settings provides account preferences, device/session controls and supported personal-data export/deletion requests. You may also contact the team. Deletion can retain necessary unresolved financial or legal records; backups are not instantly erased. The complete retention schedule and applicable request periods are awaiting confirmation. Export download links expire; expiry alone does not establish every retained copy has been deleted.', 'সেটিংসে পছন্দ, ডিভাইস/সেশন নিয়ন্ত্রণ ও সমর্থিত ব্যক্তিগত তথ্য রপ্তানি/মোছার অনুরোধ আছে। দলকেও লিখতে পারেন। অমীমাংসিত আর্থিক বা আইনি প্রয়োজনে কিছু তথ্য থাকতে পারে; ব্যাকআপ সঙ্গে সঙ্গে মোছে না। সম্পূর্ণ সংরক্ষণের সময়সূচি ও প্রযোজ্য অনুরোধের সময়সীমা নিশ্চিত করা বাকি। রপ্তানির লিঙ্কের মেয়াদ আছে; মেয়াদ শেষ মানেই সমস্ত কপি মোছা নয়।'),
]
TERMS = [
 ('Current availability', 'বর্তমান প্রাপ্যতা', 'This is the Maison qualification service. Draft titles are restricted to authorized review. A visible format, preview or prototype does not establish a purchase, subscription, offline licence or public release. Payments, audio/video and offline access remain unavailable unless explicitly enabled and qualified.', 'এটি মেজঁর যাচাই পরিষেবা। খসড়া বই কেবল অনুমোদিত পর্যালোচনার জন্য। কোনো ফরম্যাট, নমুনা বা প্রোটোটাইপ দেখা মানেই কেনা, সদস্যতা, অফলাইন লাইসেন্স বা প্রকাশ নয়। স্পষ্টভাবে চালু ও যাচাই না করা পর্যন্ত অর্থপ্রদান, অডিও/ভিডিও ও অফলাইন ব্যবহার উপলব্ধ নয়।'),
 ('Accounts and permitted use', 'অ্যাকাউন্ট ও অনুমোদিত ব্যবহার', 'Keep your account credentials private and provide accurate account details. Use only content and actions made available to you; do not bypass access controls or redistribute protected editions. Report suspected account misuse or a content-rights concern to the team. Earnalism is intended for readers of any age. Applicable guardian authorization and child-data safeguards must be qualified before enabling account flows that require them; no blanket consent exemption is claimed.', 'অ্যাকাউন্টের গোপন তথ্য নিরাপদ রাখুন ও সঠিক তথ্য দিন। কেবল আপনার জন্য উপলব্ধ বিষয়বস্তু ও কাজ ব্যবহার করুন; প্রবেশের নিয়ম এড়াবেন না বা সুরক্ষিত সংস্করণ পুনর্বিতরণ করবেন না। অপব্যবহার বা অধিকারসংক্রান্ত প্রশ্ন দলকে জানান। যে কোনো বয়সের পাঠকের জন্য আর্নালিজম। যেখানে প্রয়োজন, শিশুর অ্যাকাউন্ট ও তথ্যের জন্য অভিভাবকের অনুমতি ও প্রযোজ্য সুরক্ষা যাচাই করে সেই সুবিধা চালু করতে হবে; সম্মতি থেকে নির্বিচার ছাড় দাবি করা হচ্ছে না।'),
 ('Content and regional access', 'বিষয়বস্তু ও আঞ্চলিক প্রবেশ', 'Availability depends on the exact edition, offered format and approved territory policy. UAE/Mainland China and pending jurisdictions are excluded from the active publication scope. Public-domain status of an original story does not automatically clear every edition, artwork or distribution action. No blanket worldwide clearance is promised.', 'প্রাপ্যতা নির্দিষ্ট সংস্করণ, ফরম্যাট ও অনুমোদিত অঞ্চলের নীতির উপর নির্ভর করে। UAE/Mainland China ও বিচারাধীন অঞ্চল বর্তমান প্রকাশের আওতার বাইরে। মূল গল্পের পাবলিক-ডোমেইন অবস্থা মানেই প্রতিটি সংস্করণ, শিল্পকর্ম বা সরবরাহের অনুমতি নয়। বিশ্বব্যাপী নির্বিচার ছাড়পত্রের প্রতিশ্রুতি নেই।'),
 ('Questions and final terms', 'প্রশ্ন ও চূড়ান্ত শর্ত', 'Contact sales@reoenterprise.org for support, privacy and rights concerns. Applicable consumer terms and any future commercial offer/refund/tax terms must be completed for the relevant enabled scope. This draft does not waive statutory rights or create unqualified commercial promises.', 'সহায়তা, গোপনীয়তা ও অধিকারসংক্রান্ত বিষয়ে sales@reoenterprise.org-এ লিখুন। প্রযোজ্য পরিষেবার জন্য ভোক্তার শর্ত এবং ভবিষ্যতের বাণিজ্যিক অফার/ফেরত/করের শর্ত সম্পূর্ণ করতে হবে। এই খসড়া আইনগত অধিকার বাতিল করে না বা অযাচাইকৃত বাণিজ্যিক প্রতিশ্রুতি দেয় না।'),
]

def _notice(request, locale, kind, sections):
    i=1 if locale=='bn' else 0
    return page(request,locale,f'web/{kind}.html',legal_title=COPY[kind+'_title'][i],legal_draft=COPY['draft'][i],legal_review=COPY['review'][i],legal_sections=[{'heading':r[i],'body':r[2+i]} for r in sections],support_configured=bool(getattr(settings,'SUPPORT_EMAIL','')),operator_address=OPERATOR_ADDRESS,grievance_role=GRIEVANCE_ROLE)

@require_GET
def privacy(request, locale):return _notice(request,locale,'privacy',PRIVACY)

@require_GET
def terms(request, locale):return _notice(request,locale,'terms',TERMS)

@require_GET
def contact(request, locale):return _notice(request,locale,'contact',[])
