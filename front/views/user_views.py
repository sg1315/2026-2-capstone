from django.contrib import auth, messages
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect, render

from base.models import User


def main(request):
    return render(request, 'pages/main.html')

def user_login(request):
    """
    로그인
    :param request:
    :return:
    """

    if request.user.is_authenticated:
        return redirect('main')

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

            return redirect('main')

        else:
            messages.error(request, '아이디 또는 비밀번호가 올바르지 않습니다.')
            return redirect('user_login')

    return render(request, 'user/user_login.html')

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
        username = request.POST.get('username').strip()
        name = request.POST.get('name')
        email = request.POST.get('email').strip()
        password = request.POST.get('password').strip()
        confirm_password = request.POST.get('confirm_password').strip()

        username_check = User.objects.filter(username=username)
        if username_check:
            return JsonResponse({'message': '현재 사용중인 아이디입니다.'}, status=400)

        if not password or not confirm_password:
            return JsonResponse({'message': '비밀번호를 입력해주세요.'}, status=400)

        if password or confirm_password:
            if password != confirm_password:
                return JsonResponse({'message': '비밀번호와 확인 비밀번호가 일치하지 않습니다.'}, status=400)

        user = User.objects.create_user(username=username, name=name, email=email, password=password, permission='1')
        user.save()

        return JsonResponse({'message': '회원가입이 완료되었습니다.'}, status=200)

    return JsonResponse({'error': '잘못된 요청입니다.'}, status=400)