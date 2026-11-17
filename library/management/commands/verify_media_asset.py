"""Bounded onboarding command, separate from request transactions and maintenance."""
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from core.api import DomainError
from library.models import Asset,Revision
from library.services import prepared_audio
from library.storage import prepare_audio_pieces

class Command(BaseCommand):
    help='Verify one uploaded audio output and prepare its immutable offline piece hashes. Requires actual measured media evidence already recorded.'
    def add_arguments(self,parser):
        parser.add_argument('asset_id')
        parser.add_argument('--max-seconds',type=int,default=300)
    def handle(self,*args,**options):
        asset=Asset.objects.select_related('revision','unit').filter(pk=options['asset_id'],kind='audio_chapter').first()
        if not asset or asset.state not in {'processing','ready'} or asset.revision.state!='draft':
            raise CommandError('Select a processing audio asset belonging to a draft revision.')
        original_version=asset.version;original_revision_version=asset.revision.version
        # This temporary in-memory state only validates a prepared sidecar; it never publishes bytes.
        asset.state='ready'
        try:
            prepared_audio(asset)
            proof=prepare_audio_pieces(asset,max_seconds=max(1,min(900,options['max_seconds'])))
        except DomainError as exc:raise CommandError(f'{exc.code}: {exc.message}') from exc
        with transaction.atomic():
            revision=Revision.objects.select_for_update().get(pk=asset.revision_id)
            current=Asset.objects.select_for_update().get(pk=asset.id)
            if revision.state!='draft' or revision.version!=original_revision_version or current.version!=original_version or current.sha256!=asset.sha256:
                raise CommandError('Asset/revision changed while verifying; retain the private output and review current state.')
            evidence=dict(revision.validation_evidence);proofs=dict(evidence.get('offline_piece_manifests',{}));proofs[str(asset.id)]=proof
            evidence['offline_piece_manifests']=proofs;revision.validation_evidence=evidence;revision.save()
            current.state='ready';current.version+=1;current.save()
        self.stdout.write(self.style.SUCCESS(f'Audio asset {asset.id} verified; offline piece manifest {proof["sha256"]}. Revision remains draft.'))
