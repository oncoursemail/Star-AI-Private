from pathlib import Path
import json
import zipfile
import hashlib
import pytest
from star.version import __version__
from star import updates

ROOT=Path(__file__).resolve().parents[1]


def test_app_and_website_and_installer_versions_agree():
    site=json.loads((ROOT/'site/version.json').read_text())
    assert site['version']==__version__
    assert f'"{__version__}"' in (ROOT/'installer/STAR.iss').read_text()


def test_site_is_real_responsive_and_has_release_links():
    page=(ROOT/'site/index.html').read_text(encoding='utf-8')
    style=(ROOT/'site/styles.css').read_text(encoding='utf-8')
    assert 'site.js' in page and 'styles.css' in page
    assert 'releases/latest' in page and 'download' in page.lower()
    assert 'aria-expanded' in page and '@media(max-width:760px)' in style
    assert 'prefers-reduced-motion' in style


def test_update_version_comparison():
    assert updates.Version('v0.5.1') > updates.Version('0.5.0')
    assert updates.Version('v1.0.0') > updates.Version('v0.12.99')
    with pytest.raises(ValueError):updates.Version('0.5.0;rm -rf')


def test_update_rejects_corrupt_release(tmp_path):
    p=tmp_path/'STAR.zip';p.write_bytes(b'fake')
    with pytest.raises(ValueError):updates._verify_asset(p,({'name':updates.ASSET,'digest':'sha256:'+'a'*64},))
    with pytest.raises(ValueError):updates._verify_asset(p,({'name':updates.ASSET},))


def test_update_extract_rejects_zip_slip_and_accepts_exe(tmp_path):
    arc=tmp_path/'release.zip'
    with zipfile.ZipFile(arc,'w') as z:z.writestr('../bad.exe','bad')
    with pytest.raises(ValueError):updates._extract_update(arc,tmp_path/'bad')
    with zipfile.ZipFile(arc,'w') as z:
        z.writestr('STAR.exe',b'dummy')
        z.writestr('_internal/runtime.dll',b'dll')
    updates._extract_update(arc,tmp_path/'good')
    assert (tmp_path/'good'/'STAR.exe').exists()


def test_windows_release_workflow_has_real_windows_installer_and_guarded_release():
    s=(ROOT/'.github/workflows/windows-desktop.yml').read_text()
    assert 'runs-on: windows-latest' in s
    assert 'installer/STAR.iss' in s
    assert 'smoke' in s.lower()
    assert 'permission-contents: write' in s and 'needs: [windows-build, windows-tests, attest-release]' in s
    assert 'gh release create' in s


def test_private_site_produces_preview_artifacts_but_never_deploys_pages():
    s=(ROOT/'.github/workflows/website-pages.yml').read_text()
    assert 'path: frontend/dist' in s
    assert 'actions/upload-pages-artifact' not in s
    assert 'actions/deploy-pages' not in s
    assert 'pages: write' not in s


def test_release_job_finds_nested_setup_artifact():
    workflow = (ROOT/'.github/workflows/windows-desktop.yml').read_text()
    assert 'find release-assets -type f -name "STAR-Setup-$TAG.exe"' in workflow
    assert 'mkdir -p release-ready' in workflow
