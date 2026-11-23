from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, resolve_url


def home_url(user):
    """
    로그인 상태에 따른 '홈' 주소 (header/footer 로고 등에서 사용)
      비로그인 -> 메인 페이지(LOGIN_URL), 로그인 -> 프로젝트 목록(LOGIN_REDIRECT_URL)
    """
    return resolve_url(settings.LOGIN_REDIRECT_URL if user.is_authenticated else settings.LOGIN_URL)


# 로그인이 필요한 화면용. 비로그인이면 메인 페이지(settings.LOGIN_URL)로 이동한다.
# (?next= 파라미터는 붙이지 않음: 로그인 후에는 항상 프로젝트 목록으로 이동)
login_required_page = login_required(redirect_field_name=None)


def anonymous_only(view_func):
    """메인/로그인/회원가입처럼 비로그인 전용 화면. 로그인 상태면 프로젝트 목록으로 보낸다."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return view_func(request, *args, **kwargs)
    return wrapper


def is_ajax(request):
    """common.js 에서 보낸 요청인지 (X-Requested-With 헤더)"""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def login_required_json(view_func):
    """
    JSON 을 돌려주는 Action view 용 로그인 체크.
    @login_required 는 HTML 로 redirect 하므로 JS 가 처리할 수 없어 401 JSON 으로 응답한다.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {'message': '로그인이 필요합니다.', 'redirect_url': resolve_url(settings.LOGIN_URL)},
                status=401,
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def json_error(message, errors=None, status=400):
    return JsonResponse({'message': message, 'errors': errors or {}}, status=status)


def json_success(message, redirect_url):
    return JsonResponse({'message': message, 'redirect_url': redirect_url})
