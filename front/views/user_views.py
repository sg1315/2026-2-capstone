from django.conf import settings
from django.db.models import Q
from django.contrib import auth, messages
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect, render

from base.models import User
from .common import anonymous_only, login_required_json


def main(request):
    return render(request, 'main/main.html')

def user_login(request):
    """
    로그인
    :param request:
    :return:
    """

    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)  # 프로젝트 목록

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        remember_session = request.POST.get('remember_session')

        user = auth.authenticate(username=username, password=password)

        if user is not None:
            auth.login(request, user)
            if remember_session:
                request.session.set_expiry(60 * 60 * 24 * 14) # 2주
            else:
                request.session.set_expiry(0)

            # 현재 세션 키 저장 (이전에 로그인된 세션은 미들웨어에서 로그아웃 처리)
            request.session.save()
            User.objects.filter(pk=user.pk).update(session_key=request.session.session_key)

            return redirect(settings.LOGIN_REDIRECT_URL)  # 로그인 후 프로젝트 목록

        else:
            messages.error(request, '아이디 또는 비밀번호가 올바르지 않습니다.')
            return redirect('user_login')

    return render(request, 'user/user_login.html')

def user_logout(request):
    """
    로그아웃
    """
    if request.method == 'POST':
        auth.logout(request)

    return redirect(settings.LOGOUT_REDIRECT_URL)  # 메인 페이지

@anonymous_only
def user_signup(request: HttpRequest):
    """
    회원가입
    """
    return render(request, 'user/user_signup.html')


def user_signup_action(request: HttpRequest):
    """
    사용자 등록
    """
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        username_check = User.objects.filter(username=username)
        if username_check:
            return JsonResponse({'message': '현재 사용중인 아이디입니다.'}, status=400)

        if not password or not confirm_password:
            return JsonResponse({'message': '비밀번호를 입력해주세요.'}, status=400)

        if password or confirm_password:
            if password != confirm_password:
                return JsonResponse({'message': '비밀번호와 확인 비밀번호가 일치하지 않습니다.'}, status=400)

        user = User.objects.create_user(username=username, name=name, email=email, password=password, is_superuser=False)
        user.save()

        return JsonResponse({'message': '회원가입이 완료되었습니다.'}, status=200)

    return JsonResponse({'error': '잘못된 요청입니다.'}, status=400)


USER_SEARCH_LIMIT = 10


@login_required_json
def user_search(request):
    """
    사용자 검색 (프로젝트 참여자 추가용, JSON 응답)
    - 아이디 또는 이름에 검색어가 포함된 사용자, 최대 10명
    - 본인·비활성 계정 제외, 이메일 등 개인정보는 돌려주지 않음
    """
    q = request.GET.get('q', '').strip().lstrip('@')
    if not q:
        return JsonResponse({'users': []})

    users = (
        User.objects.filter(is_active=True)
        .filter(Q(username__icontains=q) | Q(name__icontains=q))
        .exclude(pk=request.user.pk)
        .order_by('username')[:USER_SEARCH_LIMIT]
    )
    return JsonResponse({
        'users': [{'id': u.id, 'username': u.username, 'name': u.name or ''} for u in users],
    })
