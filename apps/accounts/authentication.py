"""DRF authentication with our JWT access tokens (drop-in for simplejwt's JWTAuthentication)."""
from rest_framework.authentication import BaseAuthentication

from .models import User
from .tokens import AuthenticationFailed, InvalidToken, TokenError, decode

AUTH_HEADER_TYPES = ('Bearer',)


class JWTAuthentication(BaseAuthentication):
    www_authenticate_realm = 'api'

    def authenticate_header(self, request):
        return f'{AUTH_HEADER_TYPES[0]} realm="{self.www_authenticate_realm}"'

    def authenticate(self, request):
        header = request.META.get('HTTP_AUTHORIZATION')
        if header is None:
            return None
        parts = header.split()
        if len(parts) == 0 or parts[0] not in AUTH_HEADER_TYPES:
            return None
        if len(parts) != 2:
            raise AuthenticationFailed('Authorization header must contain two space-delimited values',
                                       code='bad_authorization_header')
        try:
            payload = decode(parts[1], 'access')
        except TokenError as exc:
            raise InvalidToken({
                'detail': 'Given token not valid for any token type',
                'messages': [{'token_class': 'AccessToken', 'token_type': 'access', 'message': str(exc)}],
            }) from None
        user_id = payload.get('user_id')
        if user_id is None:
            raise InvalidToken('Token contained no recognizable user identification')
        try:
            user = User.objects.filter(pk=user_id).first()
        except (TypeError, ValueError):
            user = None
        if user is None:
            raise AuthenticationFailed('User not found', code='user_not_found')
        if not user.is_active:
            raise AuthenticationFailed('User is inactive', code='user_inactive')
        return user, payload
