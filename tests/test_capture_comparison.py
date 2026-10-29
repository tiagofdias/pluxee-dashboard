import unittest
from unittest.mock import patch
from scripts.compare_login_capture import extract_capture,compare_credentials
from pluxee_crypto import encrypt


class CaptureComparisonTests(unittest.TestCase):
    def setUp(self):
        self.capture={'Email':encrypt('fictional@example.test'),'Password':encrypt('fictional-password')}

    def test_matching_inputs_verified_without_network_or_decryption(self):
        with patch('requests.request',side_effect=AssertionError('No network allowed')):
            result=compare_credentials('fictional@example.test','fictional-password',self.capture)
        self.assertTrue(result['email_matches']);self.assertTrue(result['password_matches'])

    def test_password_difference_is_identified_without_an_api_attempt(self):
        result=compare_credentials('fictional@example.test','different-password',self.capture)
        self.assertTrue(result['email_matches']);self.assertFalse(result['password_matches'])

    def test_only_successful_official_login_is_selected_from_har(self):
        import json
        entry=lambda status,payload:{'request':{'url':'https://api.mobile.clients.pluxee.pt/api/user/login?idLanguage=1','postData':{'text':json.dumps(payload)}},'response':{'status':status}}
        har={'log':{'entries':[entry(200,self.capture),entry(400,{'Email':'wrong','Password':'wrong'})]}}
        self.assertEqual(extract_capture(har),self.capture)

    def test_invalid_capture_is_rejected(self):
        with self.assertRaises(ValueError):extract_capture({'log':{'entries':[]}})


if __name__=='__main__':unittest.main()
