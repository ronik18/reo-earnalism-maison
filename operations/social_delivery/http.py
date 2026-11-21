"""Bounded standard-library HTTPS transport. No request happens at import/construction."""
from dataclasses import dataclass
import http.client
import json
from pathlib import Path
import re
import ssl
from urllib.parse import urlsplit

HOSTS = {'www.googleapis.com', 'graph.facebook.com', 'rupload.facebook.com', 'api.x.com'}


@dataclass(frozen=True)
class FileSlice:
    path: Path
    offset: int
    length: int


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict
    data: dict


class _LimitedFile:
    def __init__(self, source):
        self.stream = Path(source.path).open('rb')
        self.stream.seek(source.offset)
        self.remaining = source.length

    def read(self, size=1024 * 1024):
        if self.remaining == 0:
            return b''
        data = self.stream.read(min(max(1, size), self.remaining))
        if not data:
            raise OSError('source_shorter_than_bound_upload')
        self.remaining -= len(data)
        return data

    def close(self):
        self.stream.close()


class HTTPSClient:
    """One request, no redirects/retries or credential discovery. File bodies stream."""
    def request(self, method, url, *, headers, json_body=None, body=None):
        target = urlsplit(url)
        if (target.scheme != 'https' or target.hostname not in HOSTS
                or target.port not in (None, 443) or target.username or target.password
                or target.fragment or any(c in url for c in '\r\n')):
            raise ValueError('fixed_social_api_origin_required')
        headers = dict(headers)
        if any(not isinstance(k, str) or not re.fullmatch(r'[A-Za-z0-9-]+', k)
               or '\r' in str(v) or '\n' in str(v) for k, v in headers.items()):
            raise ValueError('invalid_provider_header')
        stream = None
        if json_body is not None:
            if body is not None:
                raise ValueError('one_body_required')
            body = json.dumps(json_body, separators=(',', ':')).encode()
            headers['Content-Type'] = 'application/json'
        if isinstance(body, FileSlice):
            if body.offset < 0 or body.length < 0:
                raise ValueError('bounded_file_slice_required')
            headers['Content-Length'] = str(body.length)
            stream = _LimitedFile(body)
            body = stream
        elif isinstance(body, bytes):
            headers['Content-Length'] = str(len(body))
        connection = http.client.HTTPSConnection(target.hostname, timeout=180,
                                                  context=ssl.create_default_context())
        try:
            connection.request(method, target.path + ('?' + target.query if target.query else ''),
                               body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('provider_response_too_large')
            try:
                data = json.loads(raw) if raw else {}
            except (ValueError, UnicodeError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            return Response(response.status, {k.lower(): v for k, v in response.getheaders()}, data)
        finally:
            if stream is not None:
                stream.close()
            connection.close()
