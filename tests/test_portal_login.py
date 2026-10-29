import unittest
from unittest.mock import Mock, patch
import requests
from pluxee_portal import PORTAL, PortalSession, PortalLoginError


def response(*, json=None, text='', headers=None, status=200):
    result=Mock()
    result.ok=status<400
    result.is_redirect=False
    result.status_code=status
    result.text=text
    result.headers=headers or {}
    result.json.return_value=json
    return result


class PortalLoginTests(unittest.TestCase):
    def setUp(self):
        self.http=Mock()
        self.patch=patch('pluxee_portal.requests.Session',return_value=self.http)
        self.patch.start()
        self.client=PortalSession()
        self.http.get.side_effect=[response(text='<form id="login_form_page"></form>'),response(text='<h1>Account</h1>')]
        self.http.post.return_value=response(json={'sucesso':True,'local':'/dashboard.php'})

    def tearDown(self):
        self.client.close()
        self.patch.stop()

    def test_password_only_in_post_body_and_cookie_session_is_not_a_mobile_token(self):
        result=self.client.login('123456789','test-password')
        self.assertTrue(result['portal_login_verified'])
        self.assertFalse(result['api_claim_found'])
        args,kwargs=self.http.post.call_args
        self.assertEqual(args[0],PORTAL+'/login_processing.php')
        self.assertNotIn('test-password',args[0])
        self.assertEqual(kwargs['data']['pass'],'test-password')
        self.assertFalse(kwargs['allow_redirects'])
        self.assertNotIn('params',kwargs)

    def test_failure_does_not_retry_or_return_upstream_private_html(self):
        self.http.post.return_value=response(json={'sucesso':False,'mensagem':'<b>private upstream message</b>'})
        with self.assertRaises(PortalLoginError) as error:self.client.login('123456789','test-password')
        self.assertNotIn('private upstream',str(error.exception))
        self.assertEqual(self.http.post.call_count,1)
        self.assertFalse(self.client.authenticated)

    def test_redirect_cannot_send_session_to_another_origin(self):
        self.http.post.return_value=response(json={'sucesso':True,'local':'https://untrusted.example/account'})
        with self.assertRaises(PortalLoginError):self.client.login('123456789','test-password')
        self.assertEqual(self.http.get.call_count,1)

    def test_mobile_claim_presence_is_reported_without_exposing_value(self):
        token='private-test-token-value'
        self.http.post.return_value=response(json={'sucesso':True,'local':'/dashboard.php','data':{'ApiClaim':token}})
        result=self.client.login('123456789','test-password')
        self.assertTrue(result['api_claim_found'])
        self.assertNotIn(token,str(result))
        self.assertEqual(self.client.mobile_claim,token)
        self.client.close()
        self.assertIsNone(self.client.mobile_claim)

    def test_return_to_login_form_does_not_count_as_verified(self):
        self.http.get.side_effect=[response(),response(text='<form id="login_form_page"></form>')]
        with self.assertRaises(PortalLoginError):self.client.login('123456789','test-password')
        self.assertFalse(self.client.authenticated)

    def test_invalid_input_makes_no_network_request(self):
        with self.assertRaises(PortalLoginError):self.client.login('not-a-nif','test-password')
        self.http.get.assert_not_called();self.http.post.assert_not_called()


if __name__=='__main__':unittest.main()
