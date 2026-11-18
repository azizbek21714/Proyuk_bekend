"""JWT access/refresh tokens compatible with djangorestframework-simplejwt.

Same claims (token_type, exp, iat, jti, user_id as string), HS256 signed with SECRET_KEY,
so tokens issued by the old backend keep working. Refresh tokens rotate and the old one
is blacklisted in the store (collection `token_blacklist`, document id = jti).
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from rest_framework import exceptions, status
from rest_framework.exceptions import ErrorDetail  # noqa: F401  (kept for callers)

from apps.core.store import Set, get_store

BLACKLIST = 'token_blacklist'
ACCESS_LIFETIME = timedelta(hours=1)
REFRESH_LIFETIME = timedelta(days=30)


class TokenError(Exception):
    pass


class _DetailDictMixin:
    """Error body {"detail": ..., "code": ...[, "messages": ...]} like simplejwt."""
    default_detail = ''
    default_code = ''

    def __init__(self, detail=None, code=None):
        detail_dict = {'detail': self.default_detail, 'code': self.default_code}
        if isinstance(detail, dict):
            detail_dict.update(detail)
        elif detail is not None:
            detail_dict['detail'] = detail
        if code is not None:
            detail_dict['code'] = code
        super().__init__(detail_dict)


class AuthenticationFailed(_DetailDictMixin, exceptions.AuthenticationFailed):
    pass


class InvalidToken(AuthenticationFailed):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'Token is invalid or expired'
    default_code = 'token_not_valid'


def _now():
    return datetime.now(timezone.utc)


def _key():
    return getattr(settings, 'JWT_SIGNING_KEY', None) or settings.SECRET_KEY


def _encode(payload):
    return jwt.encode(payload, _key(), algorithm='HS256')


def _new_payload(token_type, lifetime, base=None):
    now = _now()
    payload = {'token_type': token_type, 'exp': int((now + lifetime).timestamp()),
               'iat': int(now.timestamp()), 'jti': uuid.uuid4().hex}
    for claim, value in (base or {}).items():
        if claim not in ('token_type', 'exp', 'iat', 'jti'):
            payload[claim] = value
    return payload


def decode(token, expected_type):
    try:
        payload = jwt.decode(token, _key(), algorithms=['HS256'], options={'verify_aud': False})
    except jwt.ExpiredSignatureError:
        raise TokenError('Token is expired') from None
    except jwt.InvalidTokenError:
        raise TokenError('Token is invalid') from None
    if 'token_type' not in payload:
        raise TokenError('Token has no type')
    if payload['token_type'] != expected_type:
        raise TokenError('Token has wrong type')
    if 'jti' not in payload:
        raise TokenError('Token has no id')
    return payload


def tokens_for_user(user):
    """{'access', 'refresh'} for a freshly authenticated user."""
    refresh = _new_payload('refresh', REFRESH_LIFETIME, {'user_id': str(user.pk)})
    access = _new_payload('access', ACCESS_LIFETIME, refresh)
    return {'access': _encode(access), 'refresh': _encode(refresh)}


def is_blacklisted(jti):
    return get_store().get(BLACKLIST, jti) is not None


def blacklist(payload):
    exp = datetime.fromtimestamp(payload['exp'], timezone.utc)
    get_store().commit([Set(BLACKLIST, payload['jti'], {
        'id': payload['jti'], 'user_id': payload.get('user_id'), 'exp': exp, 'blacklisted_at': _now(),
    })])


def verify_refresh(token):
    payload = decode(token, 'refresh')
    if is_blacklisted(payload['jti']):
        raise TokenError('Token is blacklisted')
    return payload


def rotate(payload):
    """Blacklist the given refresh token and issue a new pair with the same claims."""
    blacklist(payload)
    refresh = _new_payload('refresh', REFRESH_LIFETIME, payload)
    access = _new_payload('access', ACCESS_LIFETIME, refresh)
    return {'access': _encode(access), 'refresh': _encode(refresh)}
