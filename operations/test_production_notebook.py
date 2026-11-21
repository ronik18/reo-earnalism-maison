"""Canonical source snapshot and disabled Run All; no external providers/models."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from operations import build_production_notebook as builder

ROOT = Path(__file__).resolve().parents[1]

# A fresh isolated Python process avoids importing the test runner's operations
# package into the notebook kernel. Inside Run All, processes and HTTP are blocked.
ISOLATED_RUN = r'''
from pathlib import Path
import builtins,contextlib,hashlib,io,json,os,sys,tempfile
from unittest.mock import patch
notebook=json.loads(Path(sys.argv[1]).read_bytes());mode=sys.argv[2]
original_import=builtins.__import__
def guarded_import(name,*args,**kwargs):
    if name.split('.')[0] in {'torch','transformers','numpy','huggingface_hub','django','google','requests','httpx'}:
        raise AssertionError('Unexpected model/auth/framework import: '+name)
    return original_import(name,*args,**kwargs)
def runall():
    namespace={'__name__':'__main__'}
    for index,cell in enumerate(notebook['cells']):
        if cell['cell_type']=='code':exec(compile(''.join(cell['source']),f'notebook-cell-{index}','exec'),namespace)
    return namespace
with tempfile.TemporaryDirectory() as temporary:
    os.chdir(temporary)
    with patch('builtins.__import__',side_effect=guarded_import),patch('builtins.input',side_effect=AssertionError('Unexpected prompt')),patch('getpass.getpass',side_effect=AssertionError('Unexpected credential prompt')),patch('subprocess.run',side_effect=AssertionError('Unexpected subprocess')),patch('subprocess.Popen',side_effect=AssertionError('Unexpected process/install')),patch('socket.create_connection',side_effect=AssertionError('Unexpected network')),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Unexpected HTTP')),contextlib.redirect_stdout(io.StringIO()):
        if mode=='collision':
            digest=notebook['metadata']['earnalism']['bridge_source_snapshot_sha256']
            root=Path.cwd().resolve()/('earnalism-private-production-'+digest[:12])
            target=root/'operations/production_bundle.py';target.parent.mkdir(parents=True);target.write_bytes(b'OWNER_WORK_PRESERVED')
            code=''.join(next(c for c in notebook['cells'] if c.get('id')=='private-production-source')['source'])
            try:exec(compile(code,'<bridge-source>','exec'),{'__name__':'__main__'})
            except RuntimeError as exc:assert 'preserved' in str(exc)
            else:raise AssertionError('Changed source was overwritten')
            assert target.read_bytes()==b'OWNER_WORK_PRESERVED'
            assert not (root/'operations/__init__.py').exists()
        else:
            first=runall()
            assert first['ENABLE_PRIVATE_STAGING'] is False and first['PUBLICATION_ENABLED'] is False
            assert first['PRODUCTION_BUNDLE_PATH']=='' and first['MAX_GENERATION_CALLS']==0
            assert first['SOCIAL_ACTION']=='private-upload'
            if mode=='reuse':
                root=first['BRIDGE_ROOT'];before={p.relative_to(root).as_posix():p.stat().st_mtime_ns for p in root.rglob('*') if p.is_file()}
                second=runall();assert root==second['BRIDGE_ROOT']
                assert before=={p.relative_to(root).as_posix():p.stat().st_mtime_ns for p in root.rglob('*') if p.is_file()}
print('PASS: '+mode+'; no model, provider, authentication, install or child process in Run All')
'''


class ProductionNotebookTests(unittest.TestCase):
    def notebook(self):
        return json.loads((ROOT / builder.NOTEBOOK).read_bytes())

    def isolated(self, mode):
        result = subprocess.run([sys.executable, "-B", "-I", "-c", ISOLATED_RUN,
            str(ROOT / builder.NOTEBOOK), mode], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: " + mode, result.stdout)

    def test_snapshot_matches_actual_canonical_source_and_cells_are_unexecuted(self):
        builder.build(ROOT, check=True)
        notebook = self.notebook()
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                self.assertIsNone(cell["execution_count"]); self.assertEqual(cell["outputs"], [])
                compile("".join(cell["source"]), "<cell>", "exec")
        code = "".join(next(c for c in notebook["cells"] if c.get("id") == "private-production-source")["source"])
        assignments = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(code).body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, (ast.Constant, ast.List))}
        raw = base64.b64decode(assignments["BRIDGE_SOURCE_BASE64"], validate=True)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), notebook["metadata"]["earnalism"]["bridge_source_snapshot_sha256"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(set(archive.namelist()), {*builder.SOURCE_FILES, "BRIDGE-SOURCES.json"})
            for name in builder.SOURCE_FILES:
                self.assertEqual(archive.read(name), (ROOT / name).read_bytes())

    def test_saved_run_all_is_inert(self): self.isolated("default")

    def test_matching_source_is_reused_without_replacement(self): self.isolated("reuse")

    def test_changed_source_is_preserved_before_archive_writes(self): self.isolated("collision")

    def test_portable_builder_reseals_only_bridge_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (*builder.SOURCE_FILES, builder.NOTEBOOK):
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            before = json.loads((root / builder.NOTEBOOK).read_bytes())["cells"][:9]
            source = root / "operations/production_bundle.py"
            source.write_bytes(source.read_bytes() + b"\n# Isolated maintenance fixture.\n")
            original = (root / builder.NOTEBOOK).read_bytes()
            with self.assertRaisesRegex(ValueError, "SNAPSHOT_STALE"):
                builder.build(root, check=True)
            self.assertEqual((root / builder.NOTEBOOK).read_bytes(), original)
            self.assertTrue(builder.build(root)["changed"])
            builder.build(root, check=True)
            self.assertEqual(json.loads((root / builder.NOTEBOOK).read_bytes())["cells"][:9], before)


if __name__ == "__main__": unittest.main()
