"""Single preparation/private-delivery entrypoint for local and Colab use.

No command publishes, allocates compute, discovers credentials or purchases a
service. Provider credentials are supplied to an explicit private operation only.
"""
import argparse
import json
import os
from pathlib import Path
import re

from .production_bundle import BundleError, load_bundle, verify_bundle
from .production_journal import OperationJournal, JournalError

PRIVATE_SOCIAL_ACTIONS = ('start', 'upload', 'reconcile_upload', 'resume_upload',
                          'captions', 'thumbnail', 'status', 'finalize', 'stage_draft')
PRIVATE_CLI_ACTIONS = ('private-upload',) + PRIVATE_SOCIAL_ACTIONS


def _maison_transport(environ):
    from library.production_handoff import MaisonHTTP
    names = ('MAISON_ORIGIN', 'MAISON_SESSION_COOKIE', 'MAISON_CSRF_TOKEN')
    if not all(environ.get(name) for name in names):
        raise BundleError('EXISTING_MAISON_STAFF_SESSION_REQUIRED')
    return MaisonHTTP(*(environ[name] for name in names))


def execute_book_import(manifest, source_path, *, journal_dir, reconcile=False, environ=None):
    from .book_source import prepare_source
    from library.book_import_client import import_private
    prepare_source(manifest, source_path)
    if not journal_dir:
        raise BundleError('PRIVATE_JOURNAL_REQUIRED')
    transport = _maison_transport(os.environ if environ is None else environ)
    return import_private(manifest, source_path, transport, OperationJournal(journal_dir),
                          execute=True, reconcile=reconcile)


def prepare(manifest, asset_root):
    digest = verify_bundle(manifest, asset_root)
    maison = {'state': 'NOT_REQUESTED_NO_DRAFT_IDENTITY'}
    if 'edition_id' in manifest['content']:
        from library.production_handoff import prepare_handoff
        maison = prepare_handoff(manifest, asset_root)
    from .social_delivery import prepare as prepare_social
    social = prepare_social(manifest, asset_root)
    return {'schema': 'earnalism.private_production_delivery_plan.v1',
            'bundle_sha256': digest, 'private': manifest['private'],
            'maison': maison, 'social': social, 'state': 'PREPARED_NO_PROVIDER_REQUESTS',
            'provider_requests': 0, 'model_calls': 0, 'publication': False,
            'quality_acceptance_supplied_by_bridge': False}


def execute_private(manifest, asset_root, *, destination, journal_dir,
                    reconcile=False, platform=None, account=None, action='private-upload',
                    graph_version=None, environ=None):
    """Operator-only private staging. A manifest's flags are not permission."""
    digest = verify_bundle(manifest, asset_root)
    if manifest['private'] is not True:
        raise BundleError('PRIVATE_CANDIDATE_REQUIRED_NO_PUBLIC_COMMAND')
    if not journal_dir: raise BundleError('PRIVATE_JOURNAL_REQUIRED')
    env = os.environ if environ is None else environ
    journal = OperationJournal(journal_dir)
    if destination == 'maison':
        from library.production_handoff import stage_private
        transport = _maison_transport(env)
        return stage_private(manifest, asset_root, transport, journal,
                             execute=True, reconcile=reconcile)
    if destination != 'social' or action not in PRIVATE_CLI_ACTIONS:
        raise BundleError('PRIVATE_SUPPORTED_DESTINATION_ACTION_REQUIRED')
    from .social_delivery import Authority, Delivery, prepare as prepare_social
    plan = prepare_social(manifest, asset_root)
    key = str(platform) + ':' + str(account)
    selected = [d for d in plan['destinations'] if d['key'] == key]
    if len(selected) != 1: raise BundleError('EXACT_SOCIAL_DESTINATION_REQUIRED')
    # An unrelated destination must not require its credentials/API version.
    selected_plan = {**plan, 'destinations': selected}

    def token_for(provider, account_id):
        if provider != platform or account_id != account:
            raise BundleError('CREDENTIAL_DESTINATION_MISMATCH')
        value = env.get('EARNALISM_' + provider.upper() + '_ACCESS_TOKEN')
        if not value: raise BundleError('EXISTING_PROVIDER_ACCESS_REQUIRED')
        return value

    actions = frozenset(PRIVATE_SOCIAL_ACTIONS if action == 'private-upload' else (action,))
    authority = Authority(digest, key, account, actions, 'operator-private-cli')

    def authorize(grant, candidate, target, requested_action):
        return (manifest['private'] is True and grant == authority
                and candidate['candidate_sha256'] == digest and target['key'] == key
                and requested_action in actions and requested_action in PRIVATE_SOCIAL_ACTIONS)

    delivery = Delivery(selected_plan, journal, token_for, authorize,
                        graph_version=graph_version or env.get('EARNALISM_META_GRAPH_VERSION'))
    if action != 'private-upload':
        return delivery.run(key, action, execute=True, authority=authority)
    # Keep short-lived resumable capabilities in this one object/process.
    # Read processing once; later status reconciles acknowledged IDs, not uploads.
    results = []
    prefix = 'social:' + digest + ':' + key + ':'
    uploaded = journal.read(prefix + 'completed-upload') if platform == 'youtube' else None
    if uploaded is None:
        uploaded = journal.read(prefix + ('upload:0' if platform == 'youtube' else 'upload'))
    completed = uploaded is not None and uploaded['state'] == 'acknowledged'
    upload_steps = () if completed else ('start', 'upload')
    for step in upload_steps + (('finalize',) if platform == 'x' else ()):
        results.append(delivery.run(key, step, execute=True, authority=authority))
    target = selected[0]
    if platform == 'youtube' and target.get('caption_asset_id'):
        results.append(delivery.run(key, 'captions', execute=True, authority=authority))
    status = delivery.run(key, 'status', execute=True, authority=authority)
    results.append(status)
    if status.get('ready') is True:
        if platform == 'youtube' and target.get('thumbnail_asset_id'):
            results.append(delivery.run(key, 'thumbnail', execute=True, authority=authority))
        if platform == 'facebook':
            results.append(delivery.run(key, 'stage_draft', execute=True, authority=authority))
    return {'state': 'PRIVATE_STAGING_STEPS_ACKNOWLEDGED', 'destination': key,
            'steps': results, 'processing_ready': status.get('ready') is True,
            'publication': False, 'automatic_polling_or_retry': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'maison-stage', 'social-stage', 'book-import', 'provider-acceptance'))
    parser.add_argument('--bundle')
    parser.add_argument('--assets')
    parser.add_argument('--source')
    parser.add_argument('--import-manifest')
    parser.add_argument('--acceptance-observations')
    parser.add_argument('--output')
    parser.add_argument('--journal')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--reconcile', action='store_true')
    parser.add_argument('--platform', choices=('youtube', 'instagram', 'facebook', 'x'))
    parser.add_argument('--account')
    parser.add_argument('--action', choices=PRIVATE_CLI_ACTIONS, default='private-upload')
    parser.add_argument('--meta-api-version')
    args = parser.parse_args(argv)
    if args.operation == 'book-import':
        if not args.source or not args.import_manifest:
            parser.error('book-import requires --source and --import-manifest')
    elif not args.bundle or not args.assets:
        parser.error('this operation requires --bundle and --assets')
    try:
        if args.output:
            output_path = Path(args.output)
            if output_path.exists() or output_path.is_symlink() or not output_path.parent.is_dir():
                raise BundleError('NEW_RECEIPT_PATH_REQUIRED_BEFORE_DISPATCH')
        if args.operation == 'book-import':
            from .book_source import load_manifest, prepare_source
            manifest = load_manifest(args.import_manifest)
            result = (execute_book_import(manifest, args.source, journal_dir=args.journal,
                reconcile=args.reconcile) if args.execute else prepare_source(manifest, args.source))
        elif args.operation == 'provider-acceptance':
            from .provider_acceptance import AcceptanceError, prepare_acceptance
            if args.execute:
                raise AcceptanceError('LIVE_PROVIDER_ACCEPTANCE_EXECUTION_DISABLED')
            observations = load_bundle(args.acceptance_observations) if args.acceptance_observations else None
            result = prepare_acceptance(load_bundle(args.bundle), args.assets, observations=observations)
        else:
            manifest = load_bundle(args.bundle)
            if args.operation == 'prepare' or not args.execute:
                result = prepare(manifest, args.assets)
            else:
                result = execute_private(manifest, args.assets,
                    destination='maison' if args.operation == 'maison-stage' else 'social',
                    journal_dir=args.journal, reconcile=args.reconcile, platform=args.platform,
                    account=args.account, action=args.action, graph_version=args.meta_api_version)
        result = {**result, 'publication': False, 'model_calls': 0}
        raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
        if args.output:
            path = Path(args.output)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        else:
            print(raw.decode(), end='')
        return 0
    except Exception as exc:
        # Provider exception strings can carry upload capabilities or auth data.
        from library.production_handoff import HandoffError
        from .social_delivery import DeliveryError
        from .stream_delivery import StreamDeliveryError
        from .book_source import SourceError
        from .provider_acceptance import AcceptanceError
        known = isinstance(exc, (BundleError, JournalError, HandoffError, DeliveryError, StreamDeliveryError,
                                 SourceError, AcceptanceError))
        value = str(exc) if known else ''
        code = value if known and re.fullmatch(r'[A-Za-z0-9_:-]{1,128}', value) else type(exc).__name__
        print(json.dumps({'state': 'HELD', 'error_code': code,
                          'publication': False, 'automatic_retry': False}))
        return 1


if __name__ == '__main__': raise SystemExit(main())
