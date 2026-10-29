"""Authentication and account isolation without cloud/database credentials."""
import os
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch

import app as dashboard
import dashboard_auth as auth
import pluxee_mobile_auth as mobile


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'APP_ORIGIN':'http://localhost','RENDER':'','CRON_SECRET':'','TELEGRAM_WEBHOOK_SECRET':''})
        self.env.start()
        self.client=dashboard.app.test_client()
        auth._sessions.clear();auth._limits.clear()

    def tearDown(self):
        auth._sessions.clear();auth._limits.clear();self.env.stop()

    def sign_in(self,client=None,account=None):
        client=client or self.client
        account=account or mobile.MobileAccount('fake-upstream-session',123,456,'fake-card',display_name='Ana Silva')
        with patch.object(mobile,'login',return_value=account):
            result=client.post('/api/auth/login',json={'email':'user@example.test','password':'fictional-password'},headers={'X-Pluxee-Request':'1'})
        self.assertEqual(result.status_code,200)
        return account,result

    def test_every_private_api_denies_anonymous_requests(self):
        with patch.object(mobile,'login') as upstream:
            for rule in dashboard.app.url_map.iter_rules():
                if not rule.rule.startswith('/api/') or rule.rule.startswith('/api/auth/'):continue
                method='GET' if 'GET' in rule.methods else 'POST'
                response=self.client.open(rule.rule,method=method,json={})
                self.assertIn(response.status_code,(401,403),rule.rule)
                self.assertNotIn('Access-Control-Allow-Origin',response.headers)
            upstream.assert_not_called()

    def test_public_demo_and_no_file_backdoors(self):
        for path in ('/login','/demo','/auth.js','/demo-data.js'):
            response=self.client.get(path);self.assertEqual(response.status_code,200);response.close()
        for path in ('/data.json','/static/data.json','/data/transactions.json','/static/../.env'):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.client.get('/static/index.html').status_code,302)

    def test_login_cookie_is_opaque_and_password_not_stored(self):
        account,response=self.sign_in()
        self.assertIn('HttpOnly',response.headers['Set-Cookie']);self.assertIn('SameSite=Lax',response.headers['Set-Cookie'])
        self.assertNotIn('fictional-password',str(auth._sessions))
        self.assertNotIn('fake-upstream-session',response.get_data(as_text=True))
        session=self.client.get('/api/auth/session').json
        self.assertTrue(session['authenticated']);self.assertNotIn('session_id',session)
        self.assertEqual(session['display_name'],'Ana Silva')
        self.assertNotIn('personalInfo',session)
        self.assertFalse(session['push_available'])

    def test_csrf_and_cross_origin_posts_denied_before_upstream(self):
        self.sign_in()
        csrf=self.client.get('/api/auth/session').json['csrf_token']
        with patch.object(mobile.MobileAccount,'fetch_snapshot') as upstream:
            self.assertEqual(self.client.post('/api/balance',json={}).status_code,403)
            self.assertEqual(self.client.post('/api/balance',json={},headers={'X-CSRF-Token':csrf,'Origin':'https://attacker.example'}).status_code,403)
            upstream.assert_not_called()
        self.assertEqual(self.client.post('/api/auth/login',json={},headers={'X-Pluxee-Request':'1','Origin':'https://attacker.example'}).status_code,403)

    def test_authenticated_users_cannot_access_owner_monitor_logs_or_config(self):
        self.sign_in()
        csrf=self.client.get('/api/auth/session').json['csrf_token']
        for path in ('/api/notifications/start','/api/notifications/config','/api/push/test'):
            self.assertEqual(self.client.post(path,json={},headers={'X-CSRF-Token':csrf}).status_code,403)
        status=self.client.get('/api/notifications/status').json
        self.assertNotIn('last_log',status);self.assertNotIn('pid',status)

    def test_two_users_have_isolated_data_and_outages_never_use_global_cache(self):
        first=mobile.MobileAccount('session-one',1,11,'card-one')
        second=mobile.MobileAccount('session-two',2,22,'card-two')
        self.sign_in(account=first)
        other=dashboard.app.test_client();self.sign_in(client=other,account=second)
        with patch.object(first,'fetch_snapshot',return_value={'success':True,'balance':{'lunch_pass':100},'transactions':[],'updated_at':'first'}):
            self.assertEqual(self.client.get('/api/balance').json['balance']['lunch_pass'],100)
        with patch.object(second,'fetch_snapshot',side_effect=mobile.MobileUnavailable('offline')):
            self.assertEqual(other.get('/api/balance').status_code,503)
        with patch.object(first,'fetch_snapshot',side_effect=mobile.MobileUnavailable('offline')):
            result=self.client.get('/api/balance');self.assertEqual(result.status_code,200)
            self.assertTrue(result.json['cached']);self.assertEqual(result.json['balance']['lunch_pass'],100)

    def test_logout_and_expiry_revoke_session(self):
        account,_=self.sign_in();csrf=self.client.get('/api/auth/session').json['csrf_token']
        result=self.client.post('/api/auth/logout',headers={'X-Pluxee-Request':'1','X-CSRF-Token':csrf})
        self.assertEqual(result.status_code,200);self.assertFalse(account.active)
        self.assertEqual(self.client.get('/api/auth/session').status_code,401)
        account,_=self.sign_in()
        for row in auth._sessions.values():row['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.assertEqual(self.client.get('/api/balance').status_code,401);self.assertFalse(account.active)

    def test_failed_login_is_not_retried_and_rate_limited(self):
        with patch.object(mobile,'login',side_effect=mobile.MobileLoginError('Login refused')) as upstream:
            for _ in range(2):self.assertEqual(self.client.post('/api/auth/login',json={'email':'user@example.test','password':'wrong'},headers={'X-Pluxee-Request':'1'}).status_code,401)
            self.assertEqual(self.client.post('/api/auth/login',json={'email':'user@example.test','password':'wrong'},headers={'X-Pluxee-Request':'1'}).status_code,429)
            self.assertEqual(upstream.call_count,2)

    def test_no_store_headers_and_no_unconfigured_cloud_dependency(self):
        result=self.client.get('/api/auth/session')
        self.assertEqual(result.status_code,401);self.assertTrue(result.json['configured'])
        self.assertIn('no-store',result.headers['Cache-Control'])
        self.assertEqual(result.headers['X-Frame-Options'],'DENY')


if __name__=='__main__':unittest.main()
