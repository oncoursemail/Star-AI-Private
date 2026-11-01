"""Regressions for STAR's canonical public GitHub Releases channel."""
from pathlib import Path
import json

import pytest
from star import updates
from star.design_system import COLORS, contrast_ratio, MOTION_MS, stylesheet
from star.version import REPO, __version__

ROOT=Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code=status
        self.body=body or {}
    def raise_for_status(self):
        if self.status_code>=400:
            raise ValueError('GitHub error')
    def json(self):
        return self.body


class FakeClient:
    def __init__(self, responses):
        self.responses=responses
        self.called=[]
    def get(self,url,**kwargs):
        self.called.append(url)
        return self.responses[url]


def test_official_release_metadata_requires_no_authentication():
    public={"tag_name":"v9.1.0","html_url":updates.RELEASES_URL,"assets":[]}
    client=FakeClient({updates.API:FakeResponse(body=public)})
    result=updates.get_latest(client)
    assert result.available and result.repository==REPO and result.anonymous_access
    assert client.called==[updates.API]


def test_missing_release_uses_official_browser_fallback():
    client=FakeClient({updates.API:FakeResponse(404)})
    result=updates.get_latest(client)
    assert result.requires_browser and not result.available
    assert result.repository==REPO and result.url==updates.RELEASES_URL
    assert client.called==[updates.API]


def test_unverified_or_other_repository_assets_cannot_be_auto_downloaded():
    missing_proof=updates.UpdateResult(True,'9.1.0',updates.RELEASES_URL,repository=REPO)
    with pytest.raises(PermissionError):
        updates._trusted_setup_asset(missing_proof)
    wrong_repo=updates.UpdateResult(True,'9.1.0',updates.RELEASES_URL,
        repository='other-owner/not-star',anonymous_access=True)
    with pytest.raises(PermissionError):
        updates._trusted_setup_asset(wrong_repo)


@pytest.mark.parametrize("flag",["draft","prerelease"])
def test_draft_and_prerelease_are_not_auto_updates(flag):
    client=FakeClient({updates.API:FakeResponse(body={
        'tag_name':'v9.1.0','assets':[],flag:True})})
    result=updates.get_latest(client)
    assert not result.available and result.requires_browser


def test_public_web_version_and_download_location():
    site=json.loads((ROOT/'site/version.json').read_text())
    assert site['version']==__version__
    assert site['download']==f'https://github.com/{REPO}/releases/latest'
    assert REPO in (ROOT/'site/index.html').read_text()
    assert 'site.js' in (ROOT/'site/index.html').read_text()


def test_release_workflow_has_no_separate_public_mirror_job():
    job=(ROOT/'.github/workflows/windows-desktop.yml').read_text()
    assert 'publish-release:' in job and 'needs: [windows-build, attest-release]' in job
    assert 'gh release create' in job and 'SHA256SUMS.txt' in job
    assert 'publish-public:' not in job
    assert 'STAR_PUBLIC_REPO' not in job and 'STAR_PUBLIC_RELEASE_TOKEN' not in job
    assert 'permissions:\n      contents: read' in job


def test_oled_palette_is_accessible_and_icons_are_real():
    assert contrast_ratio(COLORS['text'],COLORS['canvas'])>7
    assert contrast_ratio(COLORS['muted'],COLORS['surface'])>=4.5
    assert contrast_ratio(COLORS['gold_ink'],COLORS['gold'])>=7
    style=stylesheet()
    assert 'QFrame#MetricCard' in style
    assert 'QPushButton#Nav:checked' in style
    assert MOTION_MS['message']<=220
    from star.visuals import svg_icon
    assert '<svg' in svg_icon('analytics') and '<path' in svg_icon('copy')


def test_qa_screenshots_use_real_star_theme():
    source=(ROOT/'scripts/capture_desktop_ui.py').read_text()
    assert "app.setStyleSheet(STYLE)" in source
    assert "app.setStyle('Fusion')" in source
    assert "not using its OLED stylesheet" in source


def test_no_font_offscreen_renderer_is_not_treated_as_a_real_ui_verification():
    script=(ROOT/'scripts/capture_desktop_ui.py').read_text()
    assert 'if fonts:' in script
    assert 'nonrepresentative' in script
    assert 'real desktop visual QA' in script
