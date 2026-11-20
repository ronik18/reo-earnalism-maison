import json,tempfile,unittest
from pathlib import Path
from .release import HARBOR_SCHEMA,bound_files,bound_record,check_harbor_private,sha

class BoundCandidateTests(unittest.TestCase):
 def test_changed_media_and_escaping_path_are_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();folder=root/'private';folder.mkdir();p=folder/'media.mp4';p.write_bytes(b'retained-byte-fixture')
   original=sha(p);bound_files(folder,{'media.mp4':original})
   p.write_bytes(b'changed-byte-fixture')
   with self.assertRaisesRegex(ValueError,'Changed or escaping'):bound_files(folder,{'media.mp4':original})
   outside=root/'outside.mp4';outside.write_bytes(b'outside')
   with self.assertRaisesRegex(ValueError,'Changed or escaping'):bound_files(folder,{'../outside.mp4':sha(outside)})

 def test_new_receipt_binding_rejects_changed_file_and_symlink_escape(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();folder=root/'studio';folder.mkdir();p=folder/'receipt.json';p.write_text('{}')
   item={'path':str(p),'sha256':sha(p)};self.assertEqual(bound_record(item,folder),p)
   p.write_text('{"changed":true}')
   with self.assertRaisesRegex(ValueError,'Changed or escaping'):bound_record(item,folder)
   outside=root/'outside.json';outside.write_text('{}');link=folder/'linked.json';link.symlink_to(outside)
   with self.assertRaisesRegex(ValueError,'Changed or escaping'):bound_record({'path':str(link),'sha256':sha(outside)},folder)

 def test_corrected_pair_rejects_actual_capture_hold(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();cache=root/'cache.json';capture=root/'capture.json'
   cache.write_text(json.dumps({'schema':'earnalism.tides.harbor-clean-cache.v1','overlaysExcluded':['captions','brand','qualifier']}))
   capture.write_text(json.dumps({'state':'CAPTURE_HOLD'}))
   (root/'FINAL_MANIFEST.json').write_text(json.dumps({'schema':HARBOR_SCHEMA,'publication_approved':False,'uploads_or_publications':0,'clean_cache':{'path':str(cache),'sha256':sha(cache)},'independent_clean_cache_capture_review':{'path':str(capture),'sha256':sha(capture)}}))
   with self.assertRaisesRegex(ValueError,'source-pixel capture PASS'):check_harbor_private(root,root)

if __name__=='__main__':unittest.main()
