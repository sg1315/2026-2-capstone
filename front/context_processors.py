from .views.common import home_url
from .views.project_views import get_user_projects
from .views.task_views import my_tasks


def sidebar(request):
    """
    모든 템플릿에 주입하는 공통 값
      home_url              : 로고 등 '홈' 링크 (비로그인 -> 메인, 로그인 -> 프로젝트 목록)
      sidebar_project_count : sidebar 프로젝트 메뉴 옆 숫자
      sidebar_task_count    : sidebar 업무 관리 메뉴 옆 숫자 (진행 중인 내 업무)
    """
    context = {'home_url': home_url(request.user)}
    if request.user.is_authenticated:
        context['sidebar_project_count'] = get_user_projects(request.user).count()
        context['sidebar_task_count'] = my_tasks(request.user).filter(complete_flag='N').count()
    return context
