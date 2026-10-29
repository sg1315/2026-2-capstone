from django.urls import path

from .views import main_views
from .views import user_views


urlpatterns = [
    #index
    path('index', main_views.index, name='index'),

    # 메인
    path('', main_views.main, name="main"),

    # 로그인
    path('user/login/', user_views.user_login, name="user_login"),
    path('user/signup/', user_views.user_signup, name='user_signup'),


]