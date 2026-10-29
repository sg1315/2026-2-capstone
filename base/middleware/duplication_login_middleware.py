from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import redirect

class DuplicationLoginMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            current_session_key = request.session.session_key
            valid_session_key = request.user.session_key

            # DB에 저장된 세션 키와 현재 기기의 세션 키가 다르면(다른 기기 로그인)
            if valid_session_key and valid_session_key != current_session_key:
                logout(request)
                messages.error(request, "다른 기기에서 접속하여 로그아웃 되었습니다.")
                return redirect('user_login')

        response = self.get_response(request)
        return response
