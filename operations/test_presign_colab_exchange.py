"""presign_colab_exchange: one short-lived, single-object R2 URL for a Colab exchange (no network)."""
import io
import json
from contextlib import redirect_stderr
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

ACCOUNT = "0123456789abcdef0123456789abcdef"
R2 = dict(MEDIA_STORAGE_BACKEND="r2", R2_ENDPOINT_URL=f"https://{ACCOUNT}.r2.cloudflarestorage.com",
          R2_PRIVATE_BUCKET="maison-private", R2_APPLICATION_KEY_ID="app-key", R2_APPLICATION_SECRET="app-secret",
          R2_UPLOAD_KEY_ID="up-key", R2_UPLOAD_SECRET="up-secret")
INPUTS = "exports/colab-exchange/bicharak/narration-film-01-r3/inputs.zip"
OUTPUTS = "exports/colab-exchange/bicharak/narration-film-01-r3/outputs.tar"


@override_settings(**R2)
class PresignColabExchangeTests(SimpleTestCase):
    def presign(self, *args):
        client = MagicMock()
        client.generate_presigned_url.return_value = "https://signed.example/fixture?X-Amz-Signature=abc"
        out, err = io.StringIO(), io.StringIO()
        with patch("boto3.client", return_value=client) as factory, redirect_stderr(err):
            call_command("presign_colab_exchange", *args, stdout=out, stderr=err)
        return client, factory, out.getvalue(), err.getvalue()

    def test_get_inputs_signs_one_object_with_the_read_client(self):
        before = datetime.now().astimezone()
        client, factory, out, err = self.presign("--key", INPUTS, "--method", "GET")
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual((data["key"], data["method"]), (INPUTS, "GET"))
        self.assertEqual(data["url"], "https://signed.example/fixture?X-Amz-Signature=abc")
        self.assertEqual(data["headers"], {})
        expires = datetime.fromisoformat(data["expires_at"])
        self.assertLessEqual(abs((expires - before - timedelta(seconds=21600)).total_seconds()), 60)
        client.generate_presigned_url.assert_called_once()
        args, kwargs = client.generate_presigned_url.call_args
        self.assertEqual(args[0], "get_object")
        self.assertEqual(kwargs["Params"]["Bucket"], "maison-private")
        self.assertEqual(kwargs["Params"]["Key"], INPUTS)
        self.assertEqual((kwargs["ExpiresIn"], kwargs["HttpMethod"]), (21600, "GET"))
        self.assertEqual(factory.call_args.kwargs["aws_access_key_id"], "app-key")
        self.assertNotIn("X-Amz-Signature", err)  # the audit line never carries the capability
        self.assertIn(INPUTS, err)

    def test_put_outputs_uses_the_upload_client_and_signs_the_content_type(self):
        client, factory, out, _ = self.presign("--key", OUTPUTS, "--method", "PUT", "--ttl-seconds", "7200")
        data = json.loads(out)
        self.assertEqual(data["headers"], {"Content-Type": "application/x-tar"})
        args, kwargs = client.generate_presigned_url.call_args
        self.assertEqual(args[0], "put_object")
        self.assertEqual(kwargs["Params"], {"Bucket": "maison-private", "Key": OUTPUTS,
                                            "ContentType": "application/x-tar"})
        self.assertEqual((kwargs["ExpiresIn"], kwargs["HttpMethod"]), (7200, "PUT"))
        self.assertEqual(factory.call_args.kwargs["aws_access_key_id"], "up-key")

    def refused(self, *args):
        client = MagicMock()
        with patch("boto3.client", return_value=client), self.assertRaises(CommandError) as ctx:
            call_command("presign_colab_exchange", *args, stdout=io.StringIO(), stderr=io.StringIO())
        client.generate_presigned_url.assert_not_called()
        return str(ctx.exception)

    def test_key_must_be_an_exchange_object(self):
        for key in ("revisions/x/inputs.zip", "exports/colab-exchange/bicharak/inputs.zip",
                    "exports/colab-exchange/Bicharak/job/inputs.zip",
                    "exports/colab-exchange/bicharak/../x/inputs.zip",
                    "exports/colab-exchange/bicharak/job/inputs.zip.bak",
                    "exports/colab-exchange/bicharak/job/manifest.json"):
            self.assertIn("key", self.refused("--key", key, "--method", "GET").lower(), key)

    def test_method_and_key_pair(self):
        self.assertIn("GET", self.refused("--key", OUTPUTS, "--method", "GET"))
        self.assertIn("PUT", self.refused("--key", INPUTS, "--method", "PUT"))
        self.assertIn("content", self.refused("--key", OUTPUTS, "--method", "PUT",
                                              "--content-type", "application/zip").lower())

    def test_ttl_is_capped(self):
        self.assertIn("ttl", self.refused("--key", INPUTS, "--method", "GET", "--ttl-seconds", "86401").lower())
        self.assertIn("ttl", self.refused("--key", INPUTS, "--method", "GET", "--ttl-seconds", "0").lower())
        _, _, out, _ = self.presign("--key", INPUTS, "--method", "GET", "--ttl-seconds", "86400")
        self.assertEqual(json.loads(out)["method"], "GET")

    @override_settings(MEDIA_STORAGE_BACKEND="local", LOCAL=True)
    def test_refused_when_storage_is_not_r2(self):
        self.assertIn("R2", self.refused("--key", INPUTS, "--method", "GET"))
