"""One-time owner-approved duplicate artifact cleanup; never runs downloaded code.

Only the combined PR preview may be deleted. Both separate packages must exist,
remain available at least as long, and pass full archive and member SHA-256 checks.
Active PR branches, the two newest runs per branch, releases, logs and source stay.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPO = 'oncoursemail/Star-AI-Private'
REPO_ID = 1412474221
OWNER_ID = '84545815'
BRANCH = 'maintenance/verified-artifact-cleanup-20261019'
APPROVAL = 'owner-approved-20261019-duplicate-previews'
API_ROOT = 'https://api.github.com/repos/' + REPO
COMBINED = 'STAR-Fast-Brain-Preview'
SETUP = 'STAR-Ultimate-Windows-Setup'
PORTABLE = 'STAR-Ultimate-Windows-Portable'
MANIFEST = 'STAR-PREVIEW-SHA256SUMS.txt'
ZIP_NAME = 'STAR-Genesis-Windows-x64.zip'
NAMES = (COMBINED, SETUP, PORTABLE)
MAX_ARCHIVE = 900_000_000
MAX_EXPANDED = 1_200_000_000
CHUNK = 4 * 1024 * 1024
DIGEST = re.compile(r'sha256:([a-f0-9]{64})\Z')
SETUP_NAME = re.compile(r'STAR-Setup-v[0-9]+\.[0-9]+\.[0-9]+\.exe\Z')
SHA = re.compile(r'[a-f0-9]{40}\Z')

class Refuse(RuntimeError):
    pass

class ApiFailure(Refuse):
    def __init__(self, code):
        self.code = code
        super().__init__('GitHub API HTTP ' + str(code))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

def timestamp(value):
    if not isinstance(value, str):
        raise Refuse('Missing timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise Refuse('Timestamp needs timezone')
    return parsed

def emit(kind, **value):
    print(json.dumps({'event': kind, **value}, sort_keys=True, ensure_ascii=True), flush=True)

def same_artifact(a, b):
    keys = ('id','name','digest','size_in_bytes','expired','created_at','expires_at','workflow_run')
    return all(a.get(k) == b.get(k) for k in keys)

def validate_artifact(a):
    if not isinstance(a, dict) or type(a.get('id')) is not int or a['id'] <= 0:
        raise Refuse('Invalid artifact identity')
    if (a.get('name') not in NAMES or a.get('expired') is not False
            or type(a.get('size_in_bytes')) is not int or not 0 < a['size_in_bytes'] <= MAX_ARCHIVE
            or not isinstance(a.get('digest'), str) or not DIGEST.fullmatch(a['digest'])):
        raise Refuse('Artifact name, digest, expiry or size not eligible')
    run = a.get('workflow_run')
    if (not isinstance(run, dict) or run.get('repository_id') != REPO_ID
            or run.get('head_repository_id') != REPO_ID
            or type(run.get('id')) is not int or run['id'] <= 0
            or not isinstance(run.get('head_branch'), str) or not run['head_branch']
            or not isinstance(run.get('head_sha'), str) or not SHA.fullmatch(run['head_sha'])):
        raise Refuse('Artifact source run identity not verified')
    timestamp(a.get('created_at')); timestamp(a.get('expires_at'))

def validate_group(group, protected, newest, now):
    if len(group) != 3 or {a.get('name') for a in group} != set(NAMES):
        raise Refuse('Incomplete/ambiguous preview copies')
    by_name = {a['name']: a for a in group}
    combined, setup, portable = [by_name[n] for n in NAMES]
    for a in group:
        validate_artifact(a)
        if a['workflow_run'] != combined['workflow_run']:
            raise Refuse('Copies were not created from the same source run')
    run = combined['workflow_run']
    if run['head_branch'] in {'main','master','star/next'} | protected or run['id'] in newest:
        raise Refuse('Active review or latest recovery build retained')
    if timestamp(combined['created_at']) > now - timedelta(hours=48):
        raise Refuse('Recent builds retained')
    expiry = timestamp(combined['expires_at'])
    if expiry <= now + timedelta(days=1):
        raise Refuse('Original expires too soon for cleanup validation')
    if any(timestamp(a['expires_at']) < expiry for a in (setup,portable)):
        raise Refuse('Surviving copies expire earlier than original')
    return [combined, setup, portable]

def candidates(artifacts, protected, now):
    by_run, by_branch = defaultdict(list), defaultdict(dict)
    for a in artifacts:
        if a.get('expired') is not False or a.get('name') not in NAMES:
            continue
        run = a.get('workflow_run') or {}
        if type(run.get('id')) is not int or not isinstance(run.get('head_branch'),str):
            continue
        by_run[run['id']].append(a)
        by_branch[run['head_branch']][run['id']] = a.get('created_at','')
    newest = set()
    for runs in by_branch.values():
        newest.update(sorted(runs, key=runs.get, reverse=True)[:2])
    good, skipped = [], Counter()
    for group in by_run.values():
        try:
            good.append(validate_group(group, protected, newest, now))
        except (Refuse, ValueError) as exc:
            skipped[str(exc)] += 1
    good.sort(key=lambda g: g[0]['created_at'])
    return good, newest, skipped

class GitHubAPI:
    def __init__(self):
        self.token = os.environ.get('GH_TOKEN','')
        if not self.token:
            raise Refuse('Temporary workflow token is missing')
        self.allowed_delete = set()

    def request(self, path='', method='GET', *, download=False):
        allowed_get = (path == '' or re.fullmatch(r'/actions/artifacts\?per_page=100&page=[1-9][0-9]*',path)
            or re.fullmatch(r'/pulls\?state=open&per_page=100&page=[1-9][0-9]*',path)
            or re.fullmatch(r'/actions/(artifacts|runs)/[1-9][0-9]*',path)
            or re.fullmatch(r'/actions/artifacts/[1-9][0-9]*/zip',path))
        if method == 'DELETE':
            match = re.fullmatch(r'/actions/artifacts/([1-9][0-9]*)',path)
            if not match or int(match[1]) not in self.allowed_delete:
                raise Refuse('Deletion was not authorized by byte verification')
        elif method != 'GET' or not allowed_get:
            raise Refuse('Endpoint is outside cleanup scope')
        req = urllib.request.Request(API_ROOT+path,method=method,headers={
            'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json',
            'X-GitHub-Api-Version':'2022-11-28','User-Agent':'STAR-owner-approved-cleanup'})
        try:
            response = opener().open(req,timeout=30)
        except urllib.error.HTTPError as exc:
            if download and exc.code == 302:
                location = exc.headers.get('Location','')
                u = urllib.parse.urlsplit(location)
                host = u.hostname or ''
                if (u.scheme != 'https' or u.port not in (None,443) or u.username or u.password
                        or not any(host.endswith(suffix) for suffix in
                                   ('.blob.core.windows.net','.actions.githubusercontent.com','.githubusercontent.com'))):
                    raise Refuse('Artifact redirect is not approved HTTPS storage') from None
                return location
            raise ApiFailure(exc.code) from None
        except (urllib.error.URLError, TimeoutError):
            raise Refuse('GitHub API unavailable') from None
        with response:
            if method == 'DELETE':
                if response.status != 204:
                    raise Refuse('Delete response was not confirmed')
                return None
            if download:
                raise Refuse('Artifact download did not use expected redirect')
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise Refuse('API response exceeds limit')
            return json.loads(raw)

    def identity(self):
        data = self.request()
        if (type(data.get('id')) is not int or data['id'] != REPO_ID
                or data.get('private') is not True or data.get('full_name') != REPO):
            raise Refuse('Private repository identity or visibility mismatch')

    def inventory(self):
        found, totals = {}, set()
        for page in range(1,101):
            data = self.request('/actions/artifacts?per_page=100&page='+str(page))
            batch, total = data.get('artifacts'), data.get('total_count')
            if not isinstance(batch,list) or len(batch)>100 or type(total) is not int:
                raise Refuse('Invalid inventory page')
            totals.add(total)
            for a in batch:
                if type(a.get('id')) is not int or a['id'] in found:
                    raise Refuse('Inventory changed during paging')
                found[a['id']] = a
            if len(batch)<100:
                if len(totals)!=1 or len(found)!=total:
                    raise Refuse('Inventory is incomplete or changing')
                return list(found.values())
        raise Refuse('Inventory pagination limit reached')

    def active_branches(self):
        branches = set()
        for page in range(1,31):
            rows = self.request('/pulls?state=open&per_page=100&page='+str(page))
            if not isinstance(rows,list) or len(rows)>100:
                raise Refuse('Cannot establish active reviews')
            for pr in rows:
                head = pr.get('head') or {}
                if type(head.get('repo',{}).get('id')) is not int:
                    raise Refuse('Active review has an unresolved source repository')
                if head['repo']['id'] == REPO_ID:
                    branches.add(head.get('ref'))
            if len(rows)<100:
                return branches
        raise Refuse('Active review pagination limit reached')

    def run_completed(self, a):
        source = a['workflow_run']
        run = self.request('/actions/runs/'+str(source['id']))
        if (run.get('status') != 'completed' or run.get('conclusion') != 'success'
                or run.get('event') != 'pull_request'
                or run.get('path') != '.github/workflows/windows-desktop.yml'
                or run.get('head_sha') != source['head_sha'] or run.get('head_branch') != source['head_branch']
                or (run.get('repository') or {}).get('id') != REPO_ID):
            raise Refuse('Original run is not a completed successful private PR build')

    def refresh(self, a):
        fresh = self.request('/actions/artifacts/'+str(a['id']))
        if not same_artifact(a,fresh):
            raise Refuse('Artifact metadata changed after verification')

    def download(self, a, directory):
        url = self.request('/actions/artifacts/'+str(a['id'])+'/zip',download=True)
        dest = directory / (str(a['id'])+'.zip')
        req = urllib.request.Request(url,headers={'User-Agent':'STAR-verified-artifact-reader'})
        h, size = hashlib.sha256(), 0
        try:
            with opener().open(req,timeout=90) as source, dest.open('xb') as out:
                if source.status != 200:
                    raise Refuse('Unexpected archive download status')
                while data := source.read(CHUNK):
                    size += len(data)
                    if size > a['size_in_bytes'] or size > MAX_ARCHIVE:
                        raise Refuse('Archive exceeds declared size')
                    h.update(data); out.write(data)
        except (urllib.error.URLError,TimeoutError):
            raise Refuse('Archive download unavailable') from None
        if size != a['size_in_bytes'] or 'sha256:'+h.hexdigest()!=a['digest']:
            raise Refuse('Archive digest or byte length mismatch')
        return dest


def inspect_zip(path):
    files, manifests, expanded = {}, [], 0
    with zipfile.ZipFile(path) as z:
        if len(z.infolist()) > 12:
            raise Refuse('Archive has unexpected files')
        for member in z.infolist():
            p = PurePosixPath(member.filename)
            if (p.is_absolute() or '..' in p.parts or '\\' in member.filename
                    or member.flag_bits & 1 or stat.S_ISLNK(member.external_attr>>16)):
                raise Refuse('Unsafe archive entry')
            if member.is_dir():
                if p.as_posix().rstrip('/') != 'dist':
                    raise Refuse('Unexpected archive directory')
                continue
            name = p.name
            if name not in {MANIFEST,ZIP_NAME} and not SETUP_NAME.fullmatch(name):
                raise Refuse('Archive contains non-release files')
            if member.filename not in (name,'dist/'+name) or name in files:
                raise Refuse('Archive filename collision or unexpected prefix')
            expanded += member.file_size
            if member.file_size<1 or expanded>MAX_EXPANDED:
                raise Refuse('Expanded archive limit exceeded')
            digest, count, content = hashlib.sha256(), 0, bytearray()
            with z.open(member) as src:
                while chunk := src.read(CHUNK):
                    count += len(chunk)
                    if count>member.file_size:
                        raise Refuse('Unexpected expanded size')
                    digest.update(chunk)
                    if name == MANIFEST:
                        if count>4096:
                            raise Refuse('Oversized checksum manifest')
                        content.extend(chunk)
            if count!=member.file_size:
                raise Refuse('Truncated archive member')
            files[name] = {'sha256':digest.hexdigest(),'size':count}
            if name == MANIFEST:
                manifests.append(bytes(content))
    if len(manifests)!=1:
        raise Refuse('Exactly one checksum manifest is required')
    expected = {}
    for line in manifests[0].decode('utf-8-sig').splitlines():
        match = re.fullmatch(r'([a-fA-F0-9]{64})  (STAR-[A-Za-z0-9.\-]+)',line)
        if not match or match[2] in expected:
            raise Refuse('Invalid or repeated checksum entry')
        expected[match[2]]=match[1].lower()
    if (len(expected)!=2 or ZIP_NAME not in expected
            or sum(bool(SETUP_NAME.fullmatch(x)) for x in expected)!=1):
        raise Refuse('Unexpected checksum file list')
    for name, info in files.items():
        if name!=MANIFEST and expected.get(name)!=info['sha256']:
            raise Refuse('Surviving binary fails original Windows checksum')
    return files, expected


def verify_archives(paths):
    a,b,c = [inspect_zip(p) for p in paths]
    setup_name = next(name for name in a[1] if SETUP_NAME.fullmatch(name))
    if (set(a[0]) != {MANIFEST,setup_name,ZIP_NAME}
            or set(b[0]) != {MANIFEST,setup_name} or set(c[0]) != {MANIFEST,ZIP_NAME}
            or a[1] != b[1] or a[1] != c[1]):
        raise Refuse('Split packages do not cover exact original contents')
    for name in (setup_name,MANIFEST):
        if a[0][name]!=b[0][name]:
            raise Refuse('Installer copy differs from original')
    for name in (ZIP_NAME,MANIFEST):
        if a[0][name]!=c[0][name]:
            raise Refuse('Portable copy differs from original')
    return a[1]


def apply_one(api, group, newest):
    now = datetime.now(timezone.utc)
    group = validate_group(group, api.active_branches(), newest, now)
    combined, setup, portable = group
    api.run_completed(combined)
    for a in group:
        api.refresh(a)
    with tempfile.TemporaryDirectory(prefix='star-verified-artifacts-') as temp:
        with ThreadPoolExecutor(max_workers=3) as pool:
            paths = list(pool.map(lambda a:api.download(a,Path(temp)),group))
        expected = verify_archives(paths)
    api.identity()
    validate_group(group,api.active_branches(),newest,datetime.now(timezone.utc))
    api.run_completed(combined)
    for a in group:
        api.refresh(a)
    receipt = {'run_id':combined['workflow_run']['id'],'source_sha':combined['workflow_run']['head_sha'],
        'deleted_id':combined['id'],'kept_ids':[setup['id'],portable['id']],
        'reported_bytes':combined['size_in_bytes'],'verified_binary_sha256':expected,
        'archive_sha256':{str(a['id']):a['digest'] for a in group}}
    emit('verified-before-delete',**receipt)
    api.allowed_delete.add(combined['id'])
    api.request('/actions/artifacts/'+str(combined['id']),method='DELETE')
    api.allowed_delete.remove(combined['id'])
    try:
        api.request('/actions/artifacts/'+str(combined['id']))
    except ApiFailure as exc:
        if exc.code != 404:
            raise
    else:
        raise Refuse('Deleted artifact is still visible; stop for reconciliation')
    for a in (setup,portable):
        api.refresh(a)
    emit('deleted-and-survivors-confirmed',**receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--limit',type=int,default=2)
    args=parser.parse_args()
    if not 1<=args.limit<=600:
        raise Refuse('Cleanup batch limit must be 1..600')
    if args.apply and (os.environ.get('STAR_CLEANUP_APPROVAL') != APPROVAL
        or os.environ.get('GITHUB_REPOSITORY') != REPO
        or os.environ.get('GITHUB_REF') != 'refs/heads/'+BRANCH
        or os.environ.get('GITHUB_ACTOR_ID') != OWNER_ID):
        raise Refuse('Owner approval and exact maintenance context are required')
    started=time.monotonic()
    api=GitHubAPI(); api.identity()
    artifacts=api.inventory()
    groups,newest,skipped=candidates(artifacts,api.active_branches(),datetime.now(timezone.utc))
    plan={'repo':REPO,'inventory_count':len(artifacts),'retained_bytes':sum(a['size_in_bytes'] for a in artifacts if not a['expired']),
          'eligible_groups':len(groups),'eligible_bytes':sum(g[0]['size_in_bytes'] for g in groups),
          'exclusions':dict(skipped),'mode':'apply' if args.apply else 'plan',
          'sample_ids':[g[0]['id'] for g in groups[:8]]}
    emit('plan',**plan)
    deleted, failed, attempted_bytes = [], [], 0
    try:
        if args.apply:
            for group in groups[:args.limit]:
                needed=sum(a['size_in_bytes'] for a in group)
                if time.monotonic()-started>1100 or attempted_bytes+needed>120*1024**3:
                    emit('budget-stop',elapsed_seconds=round(time.monotonic()-started,1));break
                attempted_bytes+=needed
                try:
                    deleted.append(apply_one(api,group,newest))
                except (Refuse,ValueError,KeyError,zipfile.BadZipFile,OSError) as exc:
                    reason=str(exc) if isinstance(exc,Refuse) else type(exc).__name__
                    failed.append({'id':group[0]['id'],'reason':reason})
                    emit('retained-on-failure',**failed[-1])
                    if len(failed)>=3:
                        break
    finally:
        result={**plan,'deleted_count':len(deleted),'deleted_reported_bytes':sum(d['reported_bytes'] for d in deleted),
                'deletions':deleted,'retained_on_failure':failed,'verified_download_bytes':attempted_bytes,
                'elapsed_seconds':round(time.monotonic()-started,1),'released':False,'billed_savings_known':False}
        emit('final',**result)
        summary=os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            text=json.dumps(result,indent=2,ensure_ascii=True).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            with open(summary,'a',encoding='utf-8') as f:
                f.write('# Owner-approved verified artifact cleanup\n<pre>'+text+'</pre>\n')
    return 1 if failed else 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Refuse as exc:
        emit('cleanup-refused',reason=str(exc));raise SystemExit(2)
