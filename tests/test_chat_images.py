"""Generated media previews never turn untrusted file paths into URL access."""
import base64
import io
from pathlib import Path
from PIL import Image
from star.chat_images import PREFIX, chat_image, preview_image

def test_generated_image_message_is_restored(tmp_path):
    folder=tmp_path/"generated-images"
    folder.mkdir()
    image=folder/"test-output.png"
    Image.new("RGB",(2000,1800),(32,55,72)).save(image)
    item=chat_image(tmp_path,PREFIX+image.name)
    assert item["image"].startswith("data:image/webp;base64,")
    decoded=base64.b64decode(item["image"].split(",",1)[1])
    opened=Image.open(io.BytesIO(decoded))
    assert opened.width <= 960 and opened.height <= 960

def test_previews_cannot_escape_generated_folder(tmp_path):
    assert "invalid" in chat_image(tmp_path,PREFIX+"../secrets.txt")["text"]
    assert "missing" in chat_image(tmp_path,PREFIX+"no-image.png")["text"]
    assert chat_image(tmp_path,"ordinary chat text") is None


class _Comfy:
    def status(self):
        return {'running': True}

    def run(self, flow, **_):
        buffer = io.BytesIO()
        Image.new("RGB", (flow['latent']['inputs']['width'], flow['latent']['inputs']['height']), (0, 200, 0)).save(buffer, "PNG")
        return [buffer.getvalue()]

    def close(self):
        pass


def test_the_reference_renders_right_after_the_save_and_the_note_exists_with_the_picture(tmp_path):
    """Issue 573: the chat reference must name a file that is on disk, complete, with its note beside it."""
    from star import image_gen
    from star.desktop_core import Settings
    made = image_gen.generate(Settings(project='Test'), 'a cow', tmp_path, seed=7, client=_Comfy())
    name = made['message'][len(PREFIX):]
    assert (tmp_path / 'generated-images' / name).is_file()
    assert (tmp_path / 'generated-images' / name).with_suffix('.json').is_file()
    assert not list((tmp_path / 'generated-images').glob('*.part'))
    shown = chat_image(tmp_path, made['message'])
    assert shown['image'].startswith('data:image/webp;base64,') and 'missing' not in shown['text']


def test_a_picture_that_is_not_on_disk_is_never_added_to_the_chat(tmp_path, monkeypatch):
    from star import chat_images, image_gen
    from star.desktop_core import Settings
    fake = {'answer': 'x', 'image': 'data:', 'message': PREFIX + 'star-20260101-000000-00001.png'}
    monkeypatch.setattr(image_gen, 'generate', lambda *a, **k: fake)
    import pytest
    with pytest.raises(RuntimeError, match='not in the STAR data folder'):
        chat_images.generate_chat_image(Settings(project='Test', image_quality=False), 'a cow', tmp_path)
