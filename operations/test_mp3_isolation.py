"""A disguised playlist must never fetch URLs during private MP3 measurement."""
from pathlib import Path
import shutil
import socket
import tempfile
import unittest

from library.production_handoff import HandoffError, measure_mp3


class MP3MeasurementIsolationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffprobe'), 'Existing ffprobe is unavailable')
    def test_disguised_playlist_cannot_contact_even_loopback(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
            listener.bind(('127.0.0.1', 0)); listener.listen(1)
            port = listener.getsockname()[1]
            path = Path(directory) / 'untrusted.mp3'
            path.write_text('#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n'
                '#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1,\n'
                f'http://127.0.0.1:{port}/audio.mp3\n#EXT-X-ENDLIST\n')
            with self.assertRaises(HandoffError):
                measure_mp3(path, timeout_seconds=1)
            listener.setblocking(False)
            try:
                connection, _ = listener.accept()
            except BlockingIOError:
                return
            connection.close()
            self.fail('The media probe contacted a URL from disguised source bytes')
