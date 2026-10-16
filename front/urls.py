from django.urls import path

from .views import user_views

urlpatterns = [
    # 메인
    path('', user_views.main, name="main"),

    # 로그인
    # path('', user_views.user_login, name="user_login"),
]