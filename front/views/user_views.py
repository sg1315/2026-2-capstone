from django.contrib import auth, messages
from django.shortcuts import redirect, render

from base.models import User

def main(request):
    return render(request, 'user/main.html')

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

        else:
            messages.error(request, '아이디 또는 비밀번호가 올바르지 않습니다.')
            return redirect('user_login')

    return render(request, 'user/user_login.html')