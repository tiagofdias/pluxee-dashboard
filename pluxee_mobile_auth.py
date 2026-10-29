"""Email/password authentication for the mobile API; secrets live only in memory."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
import ipaddress
import logging
import unicodedata
from urllib.parse import quote
import uuid

import requests
import pluxee_api
from pluxee_crypto import encrypt


log = logging.getLogger('pluxee-login')


class MobileLoginError(Exception):
    def __init__(self, message, *, stage=None, provider_code=None, http_status=None):
        super().__init__(message)
        self.stage = stage
        self.provider_code = provider_code
        self.http_status = http_status


class MobileUnavailable(Exception):
    pass


def _request(method, path, *, session_id=None, payload=None, params=None):
    headers = {'User-Agent': pluxee_api.DEFAULT_USER_AGENT, 'Accept': 'application/json'}
    if session_id:
        headers['ApiClaim'] = encrypt(session_id)
    try:
        response = requests.request(method, pluxee_api.BASE_URL + path,
            headers=headers, json=payload, params={'idLanguage': 1, **(params or {})},
            timeout=20, allow_redirects=False)
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise MobileUnavailable('A Pluxee está temporariamente indisponível.')
        try:
            result = response.json()
        except ValueError:
            log.warning('Pluxee stage=%s HTTP=%s non_json_response', 'login' if path == '/api/user/login' else 'cards', response.status_code)
            raise MobileUnavailable('Resposta inesperada da Pluxee.') from None
        if not isinstance(result, dict):
            raise MobileUnavailable('Invalid response from Pluxee.')
        if response.status_code in (400, 401, 403) or not response.ok or result.get('code') == -1:
            stage = 'login' if path == '/api/user/login' else 'cards'
            code = result.get('code') if isinstance(result.get('code'), int) else None
            # Only fixed endpoint names and numeric status codes reach the logs.
            log.warning('Pluxee stage=%s HTTP=%s code=%s', stage, response.status_code, code)
            if stage == 'cards':
                message = 'O login foi aceite, mas a API recusou a consulta dos cartões.'
            else:
                message = 'Não foi possível concluir a autenticação com a Pluxee.'
            message += f' (HTTP {response.status_code}' + (f', código {code}' if code is not None else '') + ')'
            raise MobileLoginError(message, stage=stage, provider_code=code, http_status=response.status_code)
        log.info('Pluxee stage=%s HTTP=%s code=%s', 'login' if path == '/api/user/login' else 'cards', response.status_code, result.get('code') if isinstance(result.get('code'), int) else None)
        return result
    except requests.RequestException:
        # Do not propagate request objects, payloads or URLs containing identifiers.
        raise MobileUnavailable('Não foi possível ligar à Pluxee. Tenta novamente mais tarde.') from None


@dataclass(repr=False)
class MobileAccount:
    session_id: str = field(repr=False)
    user_id: int = field(repr=False)
    benefit_id: int = field(repr=False)
    card_reference: str = field(repr=False)
    display_name: str = field(default='', repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    active: bool = True

    def close(self):
        with self.lock:
            self.active = False
            self.session_id = ''
            self.card_reference = ''
            self.display_name = ''

    def fetch_snapshot(self):
        with self.lock:
            if not self.active:
                raise MobileLoginError('A sessão terminou. Volta a entrar.')
            try:
                # Every request gets a fresh claim. IDs are encoded exactly once.
                balance = pluxee_api.get_balance(encrypt(self.session_id), quote(self.card_reference, safe=''))
                transactions = pluxee_api.get_movements(encrypt(self.session_id), quote(encrypt(str(self.benefit_id)), safe=''), num=100)
            except pluxee_api.PluxeeAuthError:
                raise MobileLoginError('A sessão Pluxee expirou. Volta a entrar.') from None
            except pluxee_api.PluxeeApiError:
                raise MobileUnavailable('Não foi possível atualizar os dados na Pluxee.') from None
            return {'success': True, 'balance': {'lunch_pass': round(balance, 2)},
                    'transactions': transactions, 'updated_at': datetime.now(timezone.utc).isoformat()}


def login(email, password, *, origin_ip='127.0.0.1'):
    if not isinstance(email, str) or '@' not in email or not 3 <= len(email) <= 254:
        raise MobileLoginError('Indica o email da tua conta Pluxee.')
    if not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise MobileLoginError('Indica a tua palavra-passe Pluxee.')
    stamp = datetime.now(timezone.utc).strftime('%A %B %Y %H:%M:%S GMT+00:00')
    try:
        origin_ip = str(ipaddress.ip_address(origin_ip))
    except ValueError:
        origin_ip = ''
    payload = {'Email': encrypt(email.strip()), 'Password': encrypt(password),
        'KeyMd5': '', 'Token': '', 'OriginDataRequest': stamp + '|' + origin_ip + '||Android',
        'DeviceUuid': str(uuid.uuid4()), 'DeviceModel': 'Pluxee web dashboard', 'Platform': 'android'}
    result = _request('POST', '/api/user/login', payload=payload)
    data = result.get('data')
    if result.get('code') != 3 or not isinstance(data, dict) or not data.get('sessionId') or not data.get('userId'):
        raise MobileLoginError('O login não foi concluído. Pode ser necessário entrar primeiro na app oficial.')
    session_id, user_id = str(data['sessionId']), int(data['userId'])
    benefits = _request('GET', '/api/benefit/v2', session_id=session_id,
                        params={'userId': encrypt(str(user_id))}).get('data')
    if not isinstance(benefits, list):
        raise MobileUnavailable('Não foi possível consultar os teus cartões.')
    meal_cards = []
    for benefit in benefits:
        service = ''.join(c for c in unicodedata.normalize('NFD', str(benefit.get('service', ''))) if not unicodedata.combining(c)).lower()
        if benefit.get('referenceC') and (benefit.get('productId') == 33 or 'refeicao' in service):
            meal_cards.append(benefit)
    if not meal_cards:
        raise MobileLoginError('Não foi encontrado um cartão refeição nesta conta.')
    if len(meal_cards) > 1:
        raise MobileLoginError('Esta conta tem vários cartões refeição. A seleção de cartão ainda não está disponível.')
    card = meal_cards[0]
    personal = data.get('personalInfo')
    personal = personal if isinstance(personal, dict) else {}
    name = ' '.join(value for key in ('name', 'surname')
                    if isinstance(value := personal.get(key), str))
    name = ' '.join(name.split())[:120]
    return MobileAccount(session_id, user_id, int(card['benefitId']), str(card['referenceC']), display_name=name)
