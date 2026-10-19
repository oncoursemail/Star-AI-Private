import copy
from datetime import datetime,timezone,timedelta
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import verified_cleanup as c

NOW=datetime.now(timezone.utc)
SETUP='STAR-Setup-v1.0.0.exe'
PACK='STAR-Genesis-Windows-x64.zip'
S=b'fake installer; never execute'
P=b'fake portable; never execute'
SUM=(hashlib.sha256(S).hexdigest()+'  '+SETUP+'\r\n'+hashlib.sha256(P).hexdigest()+'  '+PACK+'\r\n').encode()

def meta(i,name,run_id=9,branch='fix/old'):
    return {'id':i,'name':name,'digest':'sha256:'+'a'*64,'size_in_bytes':100,'expired':False,
        'created_at':(NOW-timedelta(days=5)).isoformat(),'expires_at':(NOW+timedelta(days=10)).isoformat(),
        'workflow_run':{'id':run_id,'repository_id':c.REPO_ID,'head_repository_id':c.REPO_ID,
                         'head_sha':'a'*40,'head_branch':branch}}

def group():
    return [meta(1,c.COMBINED),meta(2,c.SETUP),meta(3,c.PORTABLE)]

def write_zip(path,files):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,raw in files.items():z.writestr(name,raw)
    return path

def fixture_zips(root):
    return [write_zip(root/'combined.zip',{c.MANIFEST:SUM,'dist/'+SETUP:S,PACK:P}),
            write_zip(root/'setup.zip',{c.MANIFEST:SUM,SETUP:S}),
            write_zip(root/'portable.zip',{c.MANIFEST:SUM,PACK:P})]

class Tests(unittest.TestCase):
    def test_group_is_valid_only_when_both_copies_safe(self):
        self.assertEqual(c.validate_group(group(),set(),set(),NOW)[0]['id'],1)

    def test_protect_open_reviews_main_and_recovery(self):
        for branch,active,newest in [('main',set(),set()),('star/next',set(),set()),('fix/old',{'fix/old'},set()),('fix/old',set(),{9})]:
            g=group()
            for a in g:a['workflow_run']['head_branch']=branch
            with self.subTest(branch=branch,active=active,newest=newest),self.assertRaises(c.Refuse):
                c.validate_group(g,active,newest,NOW)

    def test_missing_or_extra_copies_refused(self):
        for g in [group()[:2],group()+[meta(4,c.SETUP)],[]]:
            with self.assertRaises(c.Refuse):c.validate_group(g,set(),set(),NOW)

    def test_changed_source_or_shorter_retention_refused(self):
        for change in ['sha','expired','early','foreign','recent','digest']:
            g=group()
            if change=='sha':g[1]['workflow_run']['head_sha']='b'*40
            if change=='expired':g[1]['expired']=True
            if change=='early':g[1]['expires_at']=(NOW+timedelta(days=2)).isoformat()
            if change=='foreign':g[1]['workflow_run']['repository_id']=1
            if change=='recent':g[0]['created_at']=NOW.isoformat()
            if change=='digest':g[1]['digest']=None
            with self.subTest(change=change),self.assertRaises(c.Refuse):c.validate_group(g,set(),set(),NOW)

    def test_two_newest_per_branch_protected(self):
        records=[]
        for j in range(4):
            g=[meta(10*j+i+1,n,run_id=10+j) for i,n in enumerate(c.NAMES)]
            for a in g:a['created_at']=(NOW-timedelta(days=8-j)).isoformat()
            records.extend(g)
        good,newest,_=c.candidates(records,set(),NOW)
        self.assertEqual(newest,{12,13})
        self.assertEqual([g[0]['workflow_run']['id'] for g in good],[10,11])

    def test_full_bytes_and_windows_checksums_match(self):
        with tempfile.TemporaryDirectory() as d:
            result=c.verify_archives(fixture_zips(Path(d)))
            self.assertEqual(result[SETUP],hashlib.sha256(S).hexdigest())
            self.assertEqual(result[PACK],hashlib.sha256(P).hexdigest())

    def test_corrupt_or_altered_survivor_cannot_delete(self):
        with tempfile.TemporaryDirectory() as d:
            paths=fixture_zips(Path(d))
            write_zip(paths[1],{c.MANIFEST:SUM,SETUP:S+b'wrong'})
            with self.assertRaises(c.Refuse):c.verify_archives(paths)

    def test_extra_file_not_discarded_as_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            paths=fixture_zips(Path(d))
            with zipfile.ZipFile(paths[0],'a') as z:z.writestr('unique-review.txt',b'important')
            with self.assertRaises(c.Refuse):c.verify_archives(paths)

    def test_path_traversal_and_ambiguous_names_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for bad in ['../'+SETUP,'/bad.exe','dist/../'+SETUP,'subdir/'+SETUP]:
                p=write_zip(Path(d)/'bad.zip',{c.MANIFEST:SUM,bad:S,PACK:P})
                with self.subTest(path=bad),self.assertRaises(c.Refuse):c.inspect_zip(p)

    def test_different_manifests_refused_even_if_binaries_match(self):
        with tempfile.TemporaryDirectory() as d:
            paths=fixture_zips(Path(d))
            write_zip(paths[1],{c.MANIFEST:SUM.replace(b'\r\n',b'\n'),SETUP:S})
            with self.assertRaises(c.Refuse):c.verify_archives(paths)

    def test_metadata_refresh_detects_drift(self):
        a=meta(1,c.COMBINED);b=copy.deepcopy(a);b['digest']='sha256:'+'b'*64
        self.assertFalse(c.same_artifact(a,b))

    def test_missing_approval_refuses_before_any_network(self):
        with patch.dict(os.environ,{},clear=True),patch('sys.argv',['verified_cleanup','--apply']),patch.object(c,'GitHubAPI') as api:
            with self.assertRaises(c.Refuse):c.main()
            api.assert_not_called()

    def test_raw_api_cannot_delete_without_byte_authorization(self):
        with patch.dict(os.environ,{'GH_TOKEN':'dummy'}):api=c.GitHubAPI()
        with patch.object(c,'opener') as network:
            with self.assertRaises(c.Refuse):api.request('/actions/artifacts/1',method='DELETE')
            with self.assertRaises(c.Refuse):api.request('/releases/1',method='DELETE')
            with self.assertRaises(c.Refuse):api.request('/issues/1',method='PATCH')
            network.assert_not_called()

    def test_verify_before_delete_and_confirm_survivors(self):
        with tempfile.TemporaryDirectory() as d:
            paths=fixture_zips(Path(d));g=group();events=[]
            class FakeAPI:
                allowed_delete=set()
                deleted=False
                def active_branches(self):return set()
                def identity(self):events.append('identity')
                def run_completed(self,a):events.append('run')
                def refresh(self,a):events.append(('refresh',a['id']))
                def download(self,a,directory):return paths[a['id']-1]
                def request(self,path,method='GET'):
                    if method=='DELETE':
                        assert path.endswith('/1') and self.allowed_delete=={1}
                        events.append('delete');self.deleted=True;return None
                    if self.deleted and path.endswith('/1'):raise c.ApiFailure(404)
                    raise AssertionError('unexpected')
            with patch.object(c,'emit'):
                out=c.apply_one(FakeAPI(),g,set())
            self.assertEqual(out['kept_ids'],[2,3])
            self.assertEqual(events[-2:],[('refresh',2),('refresh',3)])
            self.assertEqual(events.count('delete'),1)

    def test_unverified_archive_never_reaches_delete(self):
        g=group()
        class FakeAPI:
            def active_branches(self):return set()
            def run_completed(self,a):pass
            def refresh(self,a):pass
            def download(self,a,directory):raise c.Refuse('Fixture digest mismatch')
            def request(self,*args,**kwargs):raise AssertionError('No deletion permitted')
        with self.assertRaises(c.Refuse):c.apply_one(FakeAPI(),g,set())

if __name__=='__main__':unittest.main()
