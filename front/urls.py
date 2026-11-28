from django.urls import path

from .views import main_views
from .views import minutes_views
from .views import project_views
from .views import task_views
from .views import user_views


urlpatterns = [
    #index
    path('index', main_views.index, name='index'),

    # 메인
    path('', main_views.main, name="main"),

    # 로그인
    path('user/login/', user_views.user_login, name="user_login"),
    path('user/logout/', user_views.user_logout, name='user_logout'),
    path('user/signup/', user_views.user_signup, name='user_signup'),
    path('user/signupAction/', user_views.user_signup_action, name='user_signup_action'),
    path('user/search/', user_views.user_search, name='user_search'),

    # 업무 관리 (내 업무)
    path('tasks/', task_views.task_list, name='task_list'),
    path('tasks/<int:task_id>/completeAction/', task_views.task_complete_action, name='task_complete_action'),

    # 프로젝트
    path('project/', project_views.project_list, name='project_list'),
    path('project/create/', project_views.project_create, name='project_create'),
    path('project/createAction/', project_views.project_create_action, name='project_create_action'),
    path('project/<int:project_id>/', project_views.project_detail, name='project_detail'),
    path('project/<int:project_id>/update/', project_views.project_update, name='project_update'),
    path('project/<int:project_id>/updateAction/', project_views.project_update_action, name='project_update_action'),
    path('project/<int:project_id>/deleteAction/', project_views.project_delete_action, name='project_delete_action'),
    path('project/<int:project_id>/files/<int:file_id>/', project_views.project_file, name='project_file'),

    # 회의록 (프로젝트 하위)
    path('project/<int:project_id>/minutes/create/', minutes_views.minutes_create, name='minutes_create'),
    path('project/<int:project_id>/minutes/createAction/', minutes_views.minutes_create_action, name='minutes_create_action'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/', minutes_views.minutes_detail, name='minutes_detail'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/update/', minutes_views.minutes_update, name='minutes_update'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/updateAction/', minutes_views.minutes_update_action, name='minutes_update_action'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/deleteAction/', minutes_views.minutes_delete_action, name='minutes_delete_action'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/analyzeAction/', minutes_views.minutes_analyze_action, name='minutes_analyze_action'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/tasks/', minutes_views.minutes_tasks, name='minutes_tasks'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/tasks/saveAction/', minutes_views.minutes_tasks_save_action, name='minutes_tasks_save_action'),
    path('project/<int:project_id>/minutes/<int:minutes_id>/files/<int:file_id>/', minutes_views.minutes_file, name='minutes_file'),


]