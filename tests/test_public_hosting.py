import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.build_demo import build


class PublicDemoHostingTests(unittest.TestCase):
    def test_default_render_origin_is_used_when_repository_variable_is_empty(self):
        with tempfile.TemporaryDirectory(prefix='pluxee-public-test-') as directory,patch.dict(os.environ,{'PRIVATE_APP_URL':''}):
            build(directory)
            root=Path(directory)
            index=(root/'index.html').read_text(encoding='utf-8')
            login=(root/'login.html').read_text(encoding='utf-8')
            self.assertIn('data-login-url="https://pluxee-dashboard.onrender.com/login"',index)
            self.assertIn('data-private-login-url="https://pluxee-dashboard.onrender.com/login"',login)
            self.assertNotIn('<form',login)
            self.assertNotIn('<input',login)
            self.assertNotIn('/api/auth',login)
            self.assertFalse((root/'login.js').exists())
            self.assertTrue((root/'login-redirect.js').exists())
            self.assertFalse((root/'data.json').exists())

    def test_valid_deployment_override(self):
        with tempfile.TemporaryDirectory(prefix='pluxee-public-test-') as directory,patch.dict(os.environ,{'PRIVATE_APP_URL':'https://private.example.test/'}):
            build(directory)
            self.assertIn('https://private.example.test/login',(Path(directory)/'login.html').read_text())

    def test_invalid_origins_are_rejected(self):
        for origin in ('http://example.test','https://user:secret@example.test','https://example.test/path','https://example.test?secret=1'):
            with self.subTest(origin=origin),tempfile.TemporaryDirectory(prefix='pluxee-public-test-') as directory,patch.dict(os.environ,{'PRIVATE_APP_URL':origin}):
                with self.assertRaises(SystemExit):build(directory)


if __name__=='__main__':unittest.main()
