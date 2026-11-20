from django.conf import settings
from django.urls import path
from django.db import IntegrityError
from hashlib import sha256
from rest_framework.decorators import api_view, permission_classes
from rest_framework.decorators import throttle_classes
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework import serializers, status
from apps.accounts import tokens as jwt_tokens
from apps.accounts.models import User
from apps.core.odm import atomic
from config.permissions import is_application_admin, IsApplicationAdmin
from config.throttles import AuthenticationRateThrottle


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254, error_messages={
        'required': 'Elektron pochtani kiriting.',
        'blank': 'Elektron pochtani kiriting.',
        'invalid': "To'g'ri elektron pochta manzilini kiriting.",
    })
    password = serializers.CharField(trim_whitespace=False, write_only=True, error_messages={
        'required': 'Parolni kiriting.', 'blank': 'Parolni kiriting.',
    })


class SignupSerializer(LoginSerializer):
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)


def _tokens(user):
    return jwt_tokens.tokens_for_user(user)


def _user_data(user):
    # To'liq ism va lavozimni o'qituvchilar bo'limidan (email bo'yicha) olamiz
    # Ism yo'q bo'lsa — texnik login (masalan "email_3f9a…") emas, pochta ko'rsatiladi
    fio = (f"{user.first_name} {user.last_name}".strip()) or user.email or user.username
    lavozim = ''
    try:
        from apps.teachers.models import Teacher
        teacher = Teacher.objects.filter(user=user).first()
        if teacher:
            fio = teacher.full_name or fio
            lavozim = teacher.position
    except Exception:
        pass
    role = 'admin' if is_application_admin(user) else 'oqituvchi'
    if role != 'admin':
        assigned_roles = set(user.groups or [])
        role = next((name for name in ('oquv_bolimi', 'dekan', 'kafedra_mudiri') if name in assigned_roles), role)
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_staff': user.is_staff,
        'role': role,
        'fio': fio,
        'lavozim': lavozim,
    }


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthenticationRateThrottle])
def signup(request):
    if not getattr(settings, 'SIGNUP_OPEN', False):
        return Response({'detail': "Ro'yxatdan o'tish yopilgan. Kirish uchun pochta va parolni administrator beradi."},
                        status=status.HTTP_403_FORBIDDEN)
    serializer = SignupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    fields = serializer.validated_data
    email = fields['email'].lower()
    password = fields['password']
    # Django still requires an internal unique username. Deriving it from the
    # normalized email also makes simultaneous duplicate signups fail safely.
    username = 'email_' + sha256(email.encode('utf-8')).hexdigest()

    if User.objects.filter(email__iexact=email).exists():
        return Response({'email': ['Bu pochta bilan hisob allaqachon mavjud.']}, status=status.HTTP_400_BAD_REQUEST)

    try:
        validate_password(password, User(username=username, email=email,
                                        first_name=fields.get('first_name', ''),
                                        last_name=fields.get('last_name', '')))
    except ValidationError as exc:
        return Response({'password': exc.messages}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=fields.get('first_name', ''),
                last_name=fields.get('last_name', ''),
            )
            from apps.teachers.models import Teacher
            teacher = Teacher.objects.filter(email__iexact=email, user__isnull=True).first()
            if teacher:
                teacher.user = user
                teacher.save(update_fields=['user', 'edited_at'])
            else:
                Teacher.objects.create(
                    user=user, email=email,
                    full_name=user.get_full_name().strip() or email,
                )
    except IntegrityError:
        return Response({'email': ['Bu pochta bilan hisob allaqachon mavjud.']}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'user': _user_data(user), **_tokens(user)}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthenticationRateThrottle])
def login(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data['email'].lower()
    password = serializer.validated_data['password']

    account = User.objects.filter(email__iexact=email).first()
    if account is None:
        # Keep password hashing work for unknown accounts as well.
        User().set_password(password)
        return Response({'detail': "Elektron pochta yoki parol noto'g'ri."}, status=status.HTTP_401_UNAUTHORIZED)
    user = account if account.check_password(password) and account.is_active else None
    if user is None:
        return Response({'detail': "Elektron pochta yoki parol noto'g'ri."}, status=status.HTTP_401_UNAUTHORIZED)

    return Response({'user': _user_data(user), **_tokens(user)})


@api_view(['POST'])
@permission_classes([AllowAny])
def signin(request):
    return login(request._request)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    return Response({'user': _user_data(request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    refresh_token = request.data.get('refresh')
    if refresh_token:
        try:
            jwt_tokens.blacklist(jwt_tokens.decode(str(refresh_token), 'refresh'))
        except Exception:
            pass
    return Response({'detail': 'Muvaffaqiyatli chiqildi.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    user = request.user
    old_password = request.data.get('old_password', '')
    new_password = request.data.get('new_password', '')

    if not old_password or not new_password:
        return Response({'detail': 'old_password va new_password majburiy.'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.check_password(old_password):
        return Response({'detail': 'Eski parol noto\'g\'ri.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        validate_password(new_password, user)
    except ValidationError as exc:
        return Response({'detail': ' '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save()
    return Response({'detail': 'Parol muvaffaqiyatli o\'zgartirildi.', **_tokens(user)})


@api_view(['POST'])
@permission_classes([IsApplicationAdmin])
def reset_password(request):
    """
    Adminlar tomonidan foydalanuvchi parolini tiklash.
    Production'da email orqali link yuborish kerak.
    """
    # Foydalanuvchi username, user_id yoki email orqali ko'rsatilishi mumkin
    username = str(request.data.get('username', '') or '').strip()
    user_id = request.data.get('user_id')
    email = str(request.data.get('email', '') or '').strip()
    new_password = request.data.get('new_password', '')

    if not (username or user_id or email) or not new_password:
        return Response({'detail': 'Foydalanuvchi (username, user_id yoki email) va new_password majburiy.'},
                        status=status.HTTP_400_BAD_REQUEST)

    users = User.objects.all()
    if user_id:
        try:
            users = users.filter(pk=int(user_id))
        except (TypeError, ValueError):
            users = users.filter_fn(lambda u: False)
    elif username:
        users = users.filter(username=username)
    else:
        users = users.filter(email__iexact=email)
    user = users.first()
    if user is None:
        return Response({'detail': 'Foydalanuvchi topilmadi.'}, status=status.HTTP_404_NOT_FOUND)

    try:
        validate_password(new_password, user)
    except ValidationError as exc:
        return Response({'detail': ' '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save()
    return Response({'detail': 'Parol muvaffaqiyatli tiklandi.'})


class TokenRefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class TokenRefreshView(APIView):
    """Same behaviour as simplejwt's TokenRefreshView (rotation + blacklist)."""
    authentication_classes = ()
    permission_classes = (AllowAny,)
    www_authenticate_realm = 'api'

    def get_authenticate_header(self, request):
        return f'Bearer realm="{self.www_authenticate_realm}"'

    def post(self, request, *args, **kwargs):
        serializer = TokenRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            payload = jwt_tokens.verify_refresh(serializer.validated_data['refresh'])
        except jwt_tokens.TokenError as exc:
            raise jwt_tokens.InvalidToken(str(exc)) from None
        try:
            user = User.objects.filter(pk=int(payload.get('user_id'))).first()
        except (TypeError, ValueError):
            user = None
        if user is None or not user.is_active:
            raise jwt_tokens.AuthenticationFailed(
                'No active account found with the given credentials', code='no_active_account')
        return Response(jwt_tokens.rotate(payload))


urlpatterns = [
    path('signup', signup),
    path('login', login),
    path('signin', signin),
    path('me', me),
    path('logout', logout),
    path('change-password', change_password),
    path('reset-password', reset_password),
    path('refresh', TokenRefreshView.as_view()),
]
