"""Every schema_validation row of contracts/payload-examples.json validates against the reviewed OpenAPI schema."""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from library.validation import validate_schema

EXAMPLES = json.loads((Path(settings.BASE_DIR) / "contracts" / "payload-examples.json").read_text())


def at_pointer(document, pointer):
    node = document
    for part in pointer.split("/")[1:]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


class ContractExampleTests(SimpleTestCase):
    def test_schema_validation_rows_exist(self):
        self.assertGreaterEqual(len(EXAMPLES["schema_validation"]), 36)

    def test_every_schema_validation_row_validates(self):
        for row in EXAMPLES["schema_validation"]:
            with self.subTest(pointer=row["json_pointer"], schema=row["schema"]):
                validate_schema(at_pointer(EXAMPLES, row["json_pointer"]), row["schema"])

    def test_sentence_example_has_distinct_contiguous_ranges(self):
        first, second = EXAMPLES["measured_mapping_sentence_shape"]["segments"][:2]
        self.assertEqual((first["sentence_index"], second["sentence_index"]), (0, 1))
        self.assertEqual(first["end_offset_chars"], second["start_offset_chars"])
        self.assertLess(first["start_offset_chars"], first["end_offset_chars"])
        self.assertEqual(first["end_ms"], second["start_ms"])
