import base64
import unittest
from unittest.mock import Mock, patch
from urllib.parse import unquote
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives import padding

import pluxee_crypto as crypto
import pluxee_mobile_auth as mobile


def decrypt_for_test(wire):
    decryptor=Cipher(algorithms.AES(crypto.PROTOCOL_KEY),modes.CBC(wire[-16:].encode('ascii'))).decryptor()
    data=decryptor.update(base64.b64decode(wire[:-16]))+decryptor.finalize()
    unpadder=padding.PKCS7(128).unpadder()
    return (unpadder.update(data)+unpadder.finalize()).decode('utf-8')


class MobileProtocolTests(unittest.TestCase):
    def test_matches_known_vector_embedded_in_apk(self):
        self.assertEqual(crypto.encrypt('Test','j1ce6NnE6HKape1N'),'ZRaZftXG+9c78E2US+g0Ow==j1ce6NnE6HKape1N')

    def test_claims_have_fresh_random_iv_and_decode_to_same_session(self):
        wires=[crypto.encrypt('fictional-session') for _ in range(5)]
        self.assertEqual(len(set(wires)),5)
        self.assertTrue(all(decrypt_for_test(wire)=='fictional-session' for wire in wires))

    def test_login_encrypts_credentials_and_discovers_own_card(self):
        results=[{'code':3,'data':{'sessionId':'fictional-session','userId':123,'personalInfo':{'name':'Ana','surname':'Silva','email':'someone@example.test','nif':'not-for-the-browser'}}},
                 {'code':60,'data':[{'productId':33,'service':'Refeicao','benefitId':456,'referenceC':'fictional-card'}]}]
        with patch.object(mobile,'_request',side_effect=results) as upstream:
            account=mobile.login('someone@example.test','fictional-password')
        payload=upstream.call_args_list[0].kwargs['payload']
        self.assertEqual(decrypt_for_test(payload['Email']),'someone@example.test')
        self.assertEqual(decrypt_for_test(payload['Password']),'fictional-password')
        self.assertEqual(decrypt_for_test(upstream.call_args_list[1].kwargs['params']['userId']),'123')
        self.assertEqual(account.card_reference,'fictional-card')
        self.assertEqual(account.display_name,'Ana Silva')
        self.assertNotIn('password',repr(account));self.assertNotIn('fictional-session',repr(account))
        account.close()
        self.assertFalse(account.active)

    def test_no_fallback_to_server_owner_credentials(self):
        results=[{'code':3,'data':{'sessionId':'fictional-session','userId':123}}, {'code':60,'data':[]}]
        with patch.object(mobile,'_request',side_effect=results),self.assertRaises(mobile.MobileLoginError):
            mobile.login('someone@example.test','fictional-password')

    def test_card_fetch_uses_own_refs_and_distinct_claims(self):
        account=mobile.MobileAccount('fictional-session',123,456,'fake+card=ref')
        with patch.object(mobile.pluxee_api,'get_balance',return_value=123.45) as balance,patch.object(mobile.pluxee_api,'get_movements',return_value=[]) as movements:
            result=account.fetch_snapshot()
        self.assertEqual(result['balance']['lunch_pass'],123.45)
        self.assertEqual(unquote(balance.call_args.args[1]),'fake+card=ref')
        self.assertEqual(decrypt_for_test(unquote(movements.call_args.args[1])),'456')
        self.assertNotEqual(balance.call_args.args[0],movements.call_args.args[0])

    def test_provider_errors_do_not_expose_password_or_retry(self):
        response=Mock(status_code=400,ok=False)
        response.json.return_value={'code':214,'message':'private upstream text'}
        with patch.object(mobile.requests,'request',return_value=response) as upstream:
            with self.assertRaises(mobile.MobileLoginError) as caught:
                mobile.login('someone@example.test','fictional-password')
        self.assertEqual(upstream.call_count,1)
        self.assertNotIn('fictional-password',str(caught.exception))
        self.assertNotIn('private upstream',str(caught.exception))


if __name__=='__main__':unittest.main()
