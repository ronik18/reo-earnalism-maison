"""Bounded pre-produced media onboarding; never generates or publishes media."""
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from core.api import DomainError
from library.models import Asset,Revision
from library.services import prepared_audio
from library.storage import prepare_audio_pieces,verify_asset
from library.audio_preview import prepared_clip


class Command(BaseCommand):
    help='Verify one private audio/sample or pre-produced Stream video against its retained source/measurement evidence.'
    def add_arguments(self,parser):
        parser.add_argument('asset_id')
        parser.add_argument('--max-seconds',type=int,default=300)
    def handle(self,*args,**options):
        asset=Asset.objects.select_related('revision','unit').filter(pk=options['asset_id'],kind__in=['audio_chapter','preview_audio','video']).first()
        if not asset or asset.state not in {'processing','ready'} or asset.revision.state!='draft':
            raise CommandError('Select processing/ready pre-produced media belonging to a draft revision.')
        original_version=asset.version;original_revision_version=asset.revision.version
        # Temporary in-memory readiness validates the sidecar, not publication.
        asset.state='ready'
        try:
            if asset.provider=='stream':
                from library.stream import verify_video_metadata
                proof=verify_video_metadata(asset,max_seconds=max(1,min(8,options['max_seconds'])))
            elif asset.kind=='preview_audio':
                prepared_clip(asset)
                proof=verify_asset(asset,max_seconds=max(1,min(8,options['max_seconds'])))
            elif asset.kind=='audio_chapter':
                prepared_audio(asset)
                proof=prepare_audio_pieces(asset,max_seconds=max(1,min(900,options['max_seconds'])))
            else:
                raise DomainError('provider_processing_required','Video requires an exact signed Stream rendition.',409)
        except DomainError as exc:raise CommandError(f'{exc.code}: {exc.message}') from exc
        with transaction.atomic():
            revision=Revision.objects.select_for_update().get(pk=asset.revision_id)
            current=Asset.objects.select_for_update().get(pk=asset.id)
            if revision.state!='draft' or revision.version!=original_revision_version or current.version!=original_version or current.sha256!=asset.sha256:
                raise CommandError('Asset/revision changed during verification; retain outputs and review current state.')
            if asset.kind=='audio_chapter':
                evidence=dict(revision.validation_evidence);proofs=dict(evidence.get('offline_piece_manifests',{}));proofs[str(asset.id)]=proof
                evidence['offline_piece_manifests']=proofs;revision.validation_evidence=evidence;revision.save()
            elif asset.provider=='stream':
                evidence=dict(revision.validation_evidence);proofs=dict(evidence.get('media_assets',{}))
                proofs[str(asset.id)]={**proof,'provider':'stream','source_sha256':asset.sha256,
                    'unit_id':str(asset.unit_id) if asset.unit_id else None,'prepared':True,'verified_at':timezone.now().isoformat()}
                evidence['media_assets']=proofs;revision.validation_evidence=evidence;revision.save()
            current.state='ready';current.version+=1;current.save()
        self.stdout.write(self.style.SUCCESS(f'Media asset {asset.id} verified as {asset.kind}; revision remains draft.'))
