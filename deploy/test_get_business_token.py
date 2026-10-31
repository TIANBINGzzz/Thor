import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


SCRIPT = Path(__file__).with_name('get_business_token.py')
SPEC = importlib.util.spec_from_file_location('get_business_token', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class BusinessTokenLoginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / 'environments.local.md'
        self.config.write_text(
            '## 59 连接\n'
            '| 登录账号 | `admin` |\n'
            '| 登录密码 | `secret-59` |\n'
            '| 业务网页 | https://cloud.example/ai_center_web/#/ai |\n'
            '\n'
            '## appai 连接\n'
            '| 登录学校 | `湘中幼儿师范高等专科学校` |\n'
            '| 登录账号 | `admin` |\n'
            '| 登录密码 | `secret-appai` |\n'
            '| 业务网页 | https://appai.example/ai_center_web/#/ai |\n',
            encoding='utf-8',
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_loads_environment_credentials_and_keeps_appai_tenant_context(self):
        settings = MODULE.load_environment(self.config, 'appai')

        self.assertEqual(settings.account, 'admin')
        self.assertEqual(settings.password, 'secret-appai')
        self.assertEqual(settings.school, '湘中幼儿师范高等专科学校')
        self.assertEqual(settings.origin, 'https://appai.example')

    def test_59_uses_its_configured_automatic_login_payload(self):
        settings = MODULE.load_environment(self.config, '59')

        payload = MODULE.build_login_payload(settings)

        self.assertEqual(payload['type'], '1')
        self.assertEqual(payload['userCode'], 'admin')
        self.assertEqual(payload['password'], MODULE.md5_password('secret-59'))
        self.assertNotIn('captcha', payload)

    def test_appai_requires_its_current_captcha_challenge(self):
        settings = MODULE.load_environment(self.config, 'appai')

        with self.assertRaisesRegex(ValueError, 'captcha'):
            MODULE.build_login_payload(settings)

        payload = MODULE.build_login_payload(settings, captcha_id='challenge', captcha_code='A1B2')
        self.assertNotIn('type', payload)
        self.assertEqual(payload['captcha'], 'A1B2')
        self.assertEqual(payload['imgId'], 'challenge')

    def test_captcha_prompt_opens_the_downloaded_image(self):
        image = Path(self.temp.name) / 'captcha.png'
        image.write_bytes(b'image')

        with patch.object(MODULE.webbrowser, 'open', return_value=True) as open_browser, patch(
            'builtins.input', return_value='A1B2'
        ) as prompt:
            code = MODULE.prompt_for_captcha(image)

        self.assertEqual(code, 'A1B2')
        open_browser.assert_called_once_with(image.resolve().as_uri())
        prompt.assert_called_once()

    def test_token_save_is_atomic_and_readable_without_printing_it(self):
        output = Path(self.temp.name) / 'tokens' / 'appai.token'

        MODULE.save_token('private-token', output)

        self.assertEqual(MODULE.load_saved_token('appai', output), 'private-token')
        self.assertEqual(output.read_text(encoding='utf-8'), 'private-token\n')

    def test_empty_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '有效 Token'):
            MODULE.save_token('  ', Path(self.temp.name) / 'empty.token')


if __name__ == '__main__':
    unittest.main()
