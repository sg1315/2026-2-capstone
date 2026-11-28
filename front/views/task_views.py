"""
업무 관리: 로그인한 사용자에게 배정된 업무 목록 (회의록 분석 -> 업무 배정으로 만들어진 Task)
"""
import datetime

from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from base.models import ProjectHashtag, Task
from .common import is_ajax, json_error, login_required_json, login_required_page
from .project_views import get_user_projects

URGENT_DAYS = 3  # 오늘 ~ 3일 이내 마감이면 '마감 임박'


def my_tasks(user):
    """
    내 업무: 나에게 배정됐고(삭제 안 됨), 회의록이 살아 있고, 지금도 참여 중인 프로젝트의 업무
    (프로젝트에서 빠지면 그 프로젝트 업무는 더 이상 보이지 않는다)
    """
    return Task.objects.filter(
        user=user, use_flag='Y', minutes__use_flag='Y',
        minutes__project__in=get_user_projects(user),
    )


def _due_info(task, today):
    """마감일 표시용 값: task.due_date, task.d_day(남은 일수), task.due_label, task.due_badge"""
    task.due_date = timezone.localtime(task.due_at).date() if task.due_at else None
    task.d_day = (task.due_date - today).days if task.due_date else None
    if task.complete_flag == 'Y':
        task.due_label, task.due_badge = '완료', 'badge-success'
    elif task.d_day is None:
        task.due_label, task.due_badge = '기한 없음', 'badge-neutral'
    elif task.d_day < 0:
        task.due_label, task.due_badge = f'{-task.d_day}일 지연', 'badge-danger'
    elif task.d_day == 0:
        task.due_label, task.due_badge = '오늘 마감', 'badge-danger'
    elif task.d_day <= URGENT_DAYS:
        task.due_label, task.due_badge = f'D-{task.d_day}', 'badge-warning'
    else:
        task.due_label, task.due_badge = f'D-{task.d_day}', 'badge-neutral'
    return task


def task_stats(user):
    """상단 요약 카드 / 마감 알림 / 사이드바 숫자"""
    today = timezone.localdate()
    tz = timezone.get_current_timezone()
    start_of = lambda day: datetime.datetime.combine(day, datetime.time.min, tzinfo=tz)  # noqa: E731

    open_tasks = my_tasks(user).filter(complete_flag='N')
    overdue = open_tasks.filter(due_at__lt=start_of(today)).count()
    due_today = open_tasks.filter(due_at__gte=start_of(today), due_at__lt=start_of(today + datetime.timedelta(days=1))).count()
    due_soon = open_tasks.filter(
        due_at__gte=start_of(today + datetime.timedelta(days=1)),
        due_at__lt=start_of(today + datetime.timedelta(days=URGENT_DAYS + 1)),
    ).count()
    return {
        'open': open_tasks.count(),
        'done': my_tasks(user).filter(complete_flag='Y').count(),
        'overdue': overdue,
        'due_today': due_today,
        'due_soon': due_soon,
        'urgent': overdue + due_today + due_soon,
        'urgent_days': URGENT_DAYS,
    }


@login_required_page
def task_list(request):
    """
    업무 관리 (내 업무 목록)
    - tab=open : 진행 중 (기본) - 지연된 업무부터, 마감일 빠른 순, 기한 없는 업무는 맨 뒤
    - tab=done : 완료 - 최근에 완료한 순
    - q        : 업무 내용·프로젝트명·회의록명 검색 ('#'으로 시작하면 프로젝트 해시태그만)
    JS(검색/탭 전환/완료 체크) 요청이면 목록 부분(_task_items.html)만 돌려준다.
    """
    tab = request.GET.get('tab', 'open')
    if tab not in ('open', 'done'):
        tab = 'open'
    q = request.GET.get('q', '').strip()

    tasks = my_tasks(request.user).filter(complete_flag='Y' if tab == 'done' else 'N')

    keyword = q.lstrip('#').strip()
    if keyword:
        tagged_project_ids = ProjectHashtag.objects.filter(name__icontains=keyword, use_flag='Y').values('project_id')
        if q.startswith('#'):
            tasks = tasks.filter(minutes__project_id__in=tagged_project_ids)
        else:
            tasks = tasks.filter(
                Q(content__icontains=keyword) | Q(minutes__title__icontains=keyword)
                | Q(minutes__project__title__icontains=keyword) | Q(minutes__project_id__in=tagged_project_ids)
            )

    # 진행 중은 아래에서 마감일 순으로 다시 정렬 (DB 마다 NULL 정렬 위치가 달라 파이썬에서 처리)
    tasks = tasks.order_by('-updated_at', '-id') if tab == 'done' else tasks.order_by('id')
    tasks = tasks.select_related('minutes', 'minutes__project').prefetch_related(
        # 프로젝트 해시태그 (업무 -> 회의록 -> 프로젝트). 템플릿에서 task.minutes.project.active_hashtags
        Prefetch('minutes__project__hashtags',
                 queryset=ProjectHashtag.objects.filter(use_flag='Y').order_by('id'),
                 to_attr='active_hashtags'),
    )

    today = timezone.localdate()
    task_rows = [_due_info(t, today) for t in tasks]
    if tab == 'open':
        task_rows.sort(key=lambda t: (t.due_date is None, t.due_date or today))

    context = {'tasks': task_rows, 'tab': tab, 'q': q}
    if is_ajax(request):
        return render(request, 'tasks/_task_items.html', context)

    context['stats'] = task_stats(request.user)
    return render(request, 'tasks/task_list.html', context)


@require_POST
@login_required_json
def task_complete_action(request, task_id):
    """
    업무 완료 / 완료 취소 (JSON 응답). complete=Y|N
    나에게 배정된 업무만 바꿀 수 있다. 응답에 바뀐 요약 숫자와 마감 알림 HTML 을 함께 준다.
    """
    task = my_tasks(request.user).filter(pk=task_id).first()
    if task is None:
        return json_error('업무를 찾을 수 없거나 나에게 배정된 업무가 아닙니다.', status=404)

    complete = request.POST.get('complete') == 'Y'
    task.complete_flag = 'Y' if complete else 'N'
    task.updated_by = request.user
    task.save(update_fields=['complete_flag', 'updated_by', 'updated_at'])

    stats = task_stats(request.user)
    return JsonResponse({
        'message': '업무를 완료했습니다.' if complete else '업무를 진행 중으로 되돌렸습니다.',
        'stats': stats,
        'alert_html': render_to_string('tasks/_task_alert.html', {'stats': stats}, request=request),
    })
