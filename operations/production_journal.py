"""One private local dispatch journal, shared by the production handoff adapters.

Intent is fsynced before an external write. A lost response is not permission to
replay it. Credentials and temporary provider capabilities stay outside receipts.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .production_bundle import canonical_bytes


class JournalError(RuntimeError):
    pass


class JournalConflictError(JournalError):
    pass


ConflictJournalError = JournalConflictError


class UncertainOperation(JournalError):
    def __init__(self, record):
        self.record = record
        self.key = record['key']
        super().__init__('OPERATION_REQUIRES_RECONCILIATION')


def _safe(value, depth=0):
    if depth > 12:
        raise JournalError('BOUNDED_RECEIPT_REQUIRED')
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or re.search(r'(?:token|secret|password|cookie|authorization|upload_url|session_url|signed_url)', key, re.I):
                raise JournalError('CREDENTIAL_FREE_RECEIPT_REQUIRED')
            _safe(item, depth + 1)
    elif isinstance(value, list):
        for item in value: _safe(item, depth + 1)
    elif isinstance(value, str):
        if len(value) > 4096 or re.search(r'https?://|Bearer\s|-----BEGIN .*PRIVATE KEY|ya29\.|(?:token|sig|secret)=', value, re.I):
            raise JournalError('CREDENTIAL_FREE_RECEIPT_REQUIRED')
    elif value is not None and type(value) not in (int, float, bool):
        raise JournalError('JSON_RECEIPT_REQUIRED')


class OperationJournal:
    def __init__(self, directory):
        source = Path(directory)
        if source.is_symlink(): raise JournalError('PRIVATE_JOURNAL_DIRECTORY_REQUIRED')
        source.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory = source.resolve(strict=True)
        if stat.S_IMODE(self.directory.stat().st_mode) & 0o077:
            raise JournalError('JOURNAL_DIRECTORY_MODE_0700_REQUIRED')

    def _path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,256}', key):
            raise JournalError('SAFE_OPERATION_KEY_REQUIRED')
        return self.directory / (hashlib.sha256(key.encode()).hexdigest() + '.json')

    @contextmanager
    def _lock(self):
        flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(self.directory / '.lock', flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)

    def _read(self, key):
        path = self._path(key)
        if path.is_symlink(): raise JournalError('BOUNDED_PRIVATE_RECORD_REQUIRED')
        if not path.exists(): return None
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise JournalError('BOUNDED_PRIVATE_RECORD_REQUIRED')
        try: value = json.loads(path.read_bytes())
        except (ValueError, UnicodeError) as exc: raise JournalError('JOURNAL_RECORD_INVALID') from exc
        if not isinstance(value, dict) or value.get('key') != key or value.get('state') not in ('started', 'unknown', 'acknowledged') or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('fingerprint', ''))):
            raise JournalError('JOURNAL_RECORD_INVALID')
        _safe(value)
        return value

    def _write(self, key, value):
        _safe(value)
        raw = canonical_bytes(value)
        if len(raw) > 65536: raise JournalError('BOUNDED_RECEIPT_REQUIRED')
        destination = self._path(key)
        temporary = self.directory / ('.' + uuid.uuid4().hex + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, destination)
            fd = os.open(self.directory, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if temporary.exists(): temporary.unlink()

    def read(self, key):
        with self._lock(): return self._read(key)

    def begin(self, key, fingerprint):
        if not isinstance(fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', fingerprint):
            raise JournalError('REQUEST_FINGERPRINT_REQUIRED')
        with self._lock():
            old = self._read(key)
            if old:
                if old['fingerprint'] != fingerprint: raise JournalConflictError('OPERATION_INPUT_CHANGED')
                if old['state'] == 'acknowledged': return old['result']
                raise UncertainOperation(old)
            self._write(key, dict(key=key, fingerprint=fingerprint, state='started', started_epoch=time.time()))
        return None

    def acknowledge(self, key, result):
        if not isinstance(result, dict): raise JournalError('MAPPING_RECEIPT_REQUIRED')
        with self._lock():
            old = self._read(key)
            if not old: raise JournalError('INTENT_REQUIRED_BEFORE_ACK')
            if old['state'] == 'acknowledged':
                if old['result'] != result: raise JournalConflictError('ACKNOWLEDGED_RESULT_CHANGED')
                return old['result']
            self._write(key, {**old, 'state': 'acknowledged', 'result': result, 'completed_epoch': time.time()})
        return result

    def unknown(self, key, error_code):
        if not isinstance(error_code, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', error_code):
            raise JournalError('SAFE_ERROR_CODE_REQUIRED')
        with self._lock():
            old = self._read(key)
            if not old: raise JournalError('INTENT_REQUIRED_BEFORE_UNKNOWN')
            if old['state'] == 'acknowledged': raise JournalConflictError('ACKNOWLEDGED_OPERATION_IS_NOT_UNKNOWN')
            self._write(key, {**old, 'state': 'unknown', 'error_code': error_code, 'observed_epoch': time.time()})
