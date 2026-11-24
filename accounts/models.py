import uuid
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.sessions.models import Session
from django.db import models
from django.db.models.functions import Lower
from django.utils.crypto import salted_hmac


def normalize_email_address(email):
    return str(email or '').strip().casefold()


class UserManager(BaseUserManager):
    use_in_migrations = True
    def create_user(self,email,password=None,**extra):
        email = normalize_email_address(email)
        if not email: raise ValueError('An email address is required')
        user=self.model(email=email,**extra);user.set_password(password);user.save(using=self._db)
        from .email_identity import ensure_email_address
        ensure_email_address(user)
        return user
    def create_superuser(self,email,password=None,**extra):
        extra.update(is_staff=True,is_superuser=True,is_verified=True)
        return self.create_user(email,password,**extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    public_id = models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    display_name = models.CharField(max_length=100,blank=True)
    is_verified = models.BooleanField(default=False)
    guardian_managed = models.BooleanField(default=False)
    session_epoch = models.PositiveBigIntegerField(default=1)
    version = models.PositiveBigIntegerField(default=1)
    USERNAME_FIELD='email'
    REQUIRED_FIELDS=[]
    objects=UserManager()
    class Meta:
        db_table='auth_user'
        constraints=[models.UniqueConstraint(Lower('email'),name='maison_user_normalized_email_uq')]
    def save(self,*args,**kwargs):
        self.email=normalize_email_address(self.email)
        super().save(*args,**kwargs)
    def _get_session_auth_hash(self,secret=None):
        return salted_hmac('maison.accounts.User.session',f'{self.password}:{self.session_epoch}',secret=secret,algorithm='sha256').hexdigest()


class Preferences(models.Model):
    user=models.OneToOneField(User,on_delete=models.CASCADE,related_name='preferences')
    locale=models.CharField(max_length=2,default='en',choices=[('en','English'),('bn','বাংলা')])
    theme=models.CharField(max_length=12,default='light',choices=[(x,x) for x in ['light','dark','true_black']])
    reader_theme=models.CharField(max_length=12,default='light',choices=[(x,x) for x in ['light','sepia','dark','true_black']])
    reader_font_size=models.PositiveSmallIntegerField(default=20)
    reader_typeface=models.CharField(max_length=12,default='serif',choices=[('serif','Serif'),('sans','Sans')])
    reader_line_height=models.DecimalField(max_digits=3,decimal_places=2,default='1.80')
    reader_margins=models.CharField(max_length=16,default='comfortable',choices=[(x,x) for x in ['compact','comfortable','wide']])
    reader_alignment=models.CharField(max_length=12,default='start',choices=[('start','Start'),('justify','Justify')])
    reader_layout=models.CharField(max_length=12,default='scroll',choices=[('scroll','Scroll'),('paginated','Paginated')])
    audio_quality_kbps=models.PositiveSmallIntegerField(default=96)
    reduced_motion=models.BooleanField(default=False)
    low_data_mode=models.BooleanField(default=False)
    daily_goal_minutes=models.PositiveSmallIntegerField(default=15)
    interests=models.JSONField(default=list)
    goal=models.CharField(max_length=16,default='relax')
    search_filters=models.JSONField(default=dict)
    saved_filters=models.JSONField(default=list)
    version=models.PositiveBigIntegerField(default=1)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        db_table='maison_preferences'
        constraints=[models.CheckConstraint(condition=models.Q(reader_font_size__in=[16,20,23,26,30]),name='maison_pref_font_size'),
                     models.CheckConstraint(condition=models.Q(reader_line_height__gte=1.5,reader_line_height__lte=2.4),name='maison_pref_leading'),
                     models.CheckConstraint(condition=models.Q(audio_quality_kbps__in=[48,96]),name='maison_pref_audio_quality'),
                     models.CheckConstraint(condition=models.Q(daily_goal_minutes__gte=5,daily_goal_minutes__lte=120),name='maison_pref_goal')]


class Device(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='devices')
    session=models.OneToOneField(Session,to_field='session_key',db_column='session_key',null=True,on_delete=models.SET_NULL)
    token_binding_sha256=models.CharField(max_length=64)
    label=models.CharField(max_length=100,default='Browser')
    version=models.PositiveBigIntegerField(default=1)
    created_at=models.DateTimeField(auto_now_add=True)
    last_seen_at=models.DateTimeField(auto_now_add=True)
    expires_at=models.DateTimeField()
    revoked_at=models.DateTimeField(null=True)
    class Meta:
        db_table='maison_device'
        indexes=[models.Index(fields=['user','revoked_at','last_seen_at'],name='maison_device_active_idx')]


class EmailActionToken(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    user=models.ForeignKey(User,null=True,on_delete=models.CASCADE)
    email_normalized=models.EmailField()
    purpose=models.CharField(max_length=20,choices=[(x,x) for x in ['verify_email','password_reset','magic_signin']])
    token_sha256=models.CharField(max_length=64,unique=True)
    return_path=models.CharField(max_length=1024,default='/')
    created_at=models.DateTimeField(auto_now_add=True)
    expires_at=models.DateTimeField()
    consumed_at=models.DateTimeField(null=True)
    class Meta:
        db_table='maison_email_action_token'
        indexes=[models.Index(fields=['expires_at'],name='maison_email_action_expiry_idx')]


class Consent(models.Model):
    user=models.OneToOneField(User,on_delete=models.CASCADE)
    necessary_notice_version=models.CharField(max_length=64,default='local-v1')
    analytics_opt_in=models.BooleanField(default=False)
    marketing_email_opt_in=models.BooleanField(default=False)
    version=models.PositiveBigIntegerField(default=1)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: db_table='maison_consent_state'


class RateLimitBucket(models.Model):
    key_hash=models.CharField(max_length=64)
    purpose=models.CharField(max_length=40)
    window=models.BigIntegerField()
    count=models.PositiveIntegerField(default=0)
    expires_at=models.DateTimeField()
    class Meta:
        db_table='maison_rate_limit_bucket'
        constraints=[models.UniqueConstraint(fields=['key_hash','purpose','window'],name='maison_rate_bucket_uq')]


class MFARecoveryCode(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='mfa_recovery_codes')
    code_sha256=models.CharField(max_length=64,unique=True)
    created_at=models.DateTimeField(auto_now_add=True)
    used_at=models.DateTimeField(null=True)
    class Meta:
        db_table='maison_mfa_recovery_code'


class GuardianAuthorization(models.Model):
    """Purpose-bound operational permission, not independent identity proof."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    child=models.ForeignKey(User,on_delete=models.CASCADE,null=True,related_name='guardian_authorizations_received')
    prospective_subject_id=models.UUIDField(default=uuid.uuid4,editable=False,unique=True)
    claim_sha256=models.CharField(max_length=64,blank=True)
    claim_expires_at=models.DateTimeField(null=True)
    claimed_at=models.DateTimeField(null=True)
    retain_until=models.DateTimeField(null=True)
    guardian=models.ForeignKey(User,on_delete=models.CASCADE,related_name='guardian_authorizations_given')
    reviewer=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,related_name='guardian_authorizations_reviewed')
    jurisdiction=models.CharField(max_length=2)
    purpose=models.CharField(max_length=24,choices=[(x,x) for x in ('account_processing','privacy_access','privacy_delete')])
    notice_version=models.CharField(max_length=64)
    method=models.CharField(max_length=64)
    policy_sha256=models.CharField(max_length=64)
    evidence_sha256=models.CharField(max_length=64,blank=True)
    status=models.CharField(max_length=12,default='pending',choices=[(x,x) for x in ('pending','authorized','rejected','withdrawn')])
    created_at=models.DateTimeField(auto_now_add=True)
    reviewed_at=models.DateTimeField(null=True)
    expires_at=models.DateTimeField()
    withdrawn_at=models.DateTimeField(null=True)
    version=models.PositiveBigIntegerField(default=1)
    class Meta:
        db_table='maison_guardian_authorization'
        permissions=[('review_guardian_authorization','Review operational guardian authority evidence')]
        constraints=[
            models.CheckConstraint(condition=~models.Q(child=models.F('guardian')),name='maison_guardian_distinct_subjects'),
            models.CheckConstraint(condition=~models.Q(reviewer=models.F('guardian')) & ~models.Q(reviewer=models.F('child')),name='maison_guardian_independent_review'),
            models.CheckConstraint(condition=models.Q(status__in=['pending','authorized','rejected','withdrawn']),name='maison_guardian_status'),
            models.CheckConstraint(condition=models.Q(version__gte=1),name='maison_guardian_version'),
            models.CheckConstraint(condition=~models.Q(status='authorized') | (models.Q(reviewed_at__isnull=False) & ~models.Q(evidence_sha256='')),name='maison_guardian_review_evidence'),
        ]


ATTRIBUTION_SOURCES=('youtube','instagram','facebook','x','whatsapp','newsletter','google_play','podcast','school','partner','other')


class SignupAttribution(models.Model):
    """First-touch campaign for one self-registered member, from our own tagged links only.

    Captured from the allow-listed utm_* values that travel inside return_to; no cookie,
    fingerprint or third-party identifier. Reported only as aggregates (accounts.attribution).
    """
    user=models.OneToOneField(User,on_delete=models.CASCADE,primary_key=True,related_name='signup_attribution')
    source=models.CharField(max_length=16,choices=[(x,x) for x in ATTRIBUTION_SOURCES])
    campaign=models.CharField(max_length=64,blank=True)
    content=models.CharField(max_length=64,blank=True)
    landing_path=models.CharField(max_length=200,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='maison_signup_attribution'
        indexes=[models.Index(fields=['created_at','source'],name='maison_attribution_week_idx')]
        constraints=[
            models.CheckConstraint(condition=models.Q(source__in=ATTRIBUTION_SOURCES),name='maison_attribution_source'),
            models.CheckConstraint(condition=models.Q(campaign__regex=r'^([a-z0-9][a-z0-9-]{0,63})?$'),name='maison_attribution_campaign_slug'),
            models.CheckConstraint(condition=models.Q(content__regex=r'^([a-z0-9][a-z0-9-]{0,63})?$'),name='maison_attribution_content_slug'),
            models.CheckConstraint(condition=models.Q(landing_path='')|models.Q(landing_path__regex=r'^/(en|bn)/[A-Za-z0-9/_.-]{0,196}$'),name='maison_attribution_landing_path'),
        ]
