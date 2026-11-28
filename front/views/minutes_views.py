import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from base.ai.pipeline import parse_due_date, start_minutes_analysis
from base.models import Minutes, MinutesFile, Task, UserProject
from .common import json_error, json_success, login_required_json, login_required_page
from .files import (
    AUDIO_EXTENSIONS, AUDIO_MAX_SIZE, DOCUMENT_EXTENSIONS, MINUTES_DOC_MAX_COUNT, MINUTES_DOC_MAX_SIZE,
    extensions_attr, file_response, validate_upload,
)
from .project_views import get_project_or_404

# MinutesFile.DOC_TYPE_CHOICES
DOC_TYPE_DOCUMENT = '0'  # 회의 자료 (doc, ppt, excel, pdf ...)
DOC_TYPE_AUDIO = '1'     # 원본 음성파일 (AI 정리 결과는 Minutes.summary)
TASK_CONTENT_MAX_LENGTH = 1000


def get_minutes_or_404(user, project_id, minutes_id):
    """참여 중인 프로젝트의 (삭제되지 않은) 회의록. 아니면 Http404 -> (project, minutes)"""
    project = get_project_or_404(user, project_id)
    minutes = get_object_or_404(
        Minutes.objects.select_related('created_by'),
        pk=minutes_id, project=project, use_flag='Y',
    )
    return project, minutes


def can_edit_minutes(user, project, minutes):
    """회의록 수정·삭제·업무 배정 권한: 회의록 작성자 또는 프로젝트를 만든 사람"""
    return user.id in (minutes.created_by_id, project.created_by_id)


def get_editable_minutes(user, project_id, minutes_id):
    """수정/삭제용. 접근 불가면 Http404, 볼 수는 있지만 권한이 없으면 PermissionDenied"""
    project, minutes = get_minutes_or_404(user, project_id, minutes_id)
    if not can_edit_minutes(user, project, minutes):
        raise PermissionDenied('회의록 작성자나 프로젝트를 만든 사람만 수정하거나 삭제할 수 있습니다.')
    return project, minutes


def active_audio_files(minutes):
    return MinutesFile.objects.filter(minutes=minutes, doc_type=DOC_TYPE_AUDIO, use_flag='Y').order_by('id')


def active_document_files(minutes):
    return MinutesFile.objects.filter(minutes=minutes, doc_type=DOC_TYPE_DOCUMENT, use_flag='Y').order_by('id')


def project_members(project):
    """업무를 배정할 수 있는 사람 = 프로젝트 참여자"""
    return [up.user for up in
            UserProject.objects.filter(project=project, use_flag='Y').select_related('user').order_by('id')]


def _form_context():
    """생성/수정 화면 공통: JS 검사에 쓰는 제한값"""
    return {
        'audio_max_size': AUDIO_MAX_SIZE,
        'audio_extensions': extensions_attr(AUDIO_EXTENSIONS),
        'document_max_size': MINUTES_DOC_MAX_SIZE,
        'document_max_count': MINUTES_DOC_MAX_COUNT,
        'document_extensions': extensions_attr(DOCUMENT_EXTENSIONS),
    }


def _clean_minutes_post(request, kept_document_count=0):
    """
    생성/수정 공통 입력값 검증 -> (title, content, audio, documents, errors)
    - content(회의 내용)는 선택. 입력하면 AI 정리에 작성자 메모로 쓰인다.
    - kept_document_count: (수정) 삭제하지 않고 남기는 기존 회의 자료 수
    """
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()
    audio = request.FILES.get('audio')
    documents = request.FILES.getlist('documents')

    errors = {}
    if not title:
        errors['title'] = '회의록 제목을 입력해 주세요.'
    elif len(title) > 2000:
        errors['title'] = '회의록 제목은 2000자 이하로 입력해 주세요.'
    if audio:
        audio_error = validate_upload(audio, AUDIO_EXTENSIONS, AUDIO_MAX_SIZE, '음성파일')
        if audio_error:
            errors['audio'] = audio_error
    if kept_document_count + len(documents) > MINUTES_DOC_MAX_COUNT:
        errors['documents'] = f'회의 자료는 기존 파일을 포함해 최대 {MINUTES_DOC_MAX_COUNT}개까지 올릴 수 있습니다.'
    else:
        for doc in documents:
            doc_error = validate_upload(doc, DOCUMENT_EXTENSIONS, MINUTES_DOC_MAX_SIZE, '회의 자료')
            if doc_error:
                errors['documents'] = doc_error
                break
    return title, content, audio, documents, errors


def _save_file(minutes, upload, doc_type, user):
    """저장 경로(upload_to)가 minutes.id 를 쓰므로 회의록이 저장된 뒤에 호출"""
    MinutesFile.objects.create(
        minutes=minutes,
        path=upload,
        name=upload.name,
        type=upload.content_type,
        size=upload.size,
        doc_type=doc_type,
        created_by=user,
        updated_by=user,
    )


def _hide_files(files, user):
    for f in files:
        f.use_flag = 'N'
        f.updated_by = user
        f.save(update_fields=['use_flag', 'updated_by', 'updated_at'])


@login_required_page
def minutes_create(request, project_id):
    """회의록 생성 화면 (저장은 minutes_create_action). 반드시 특정 프로젝트 아래에 생성된다."""
    project = get_project_or_404(request.user, project_id)
    return render(request, 'minutes/minute_form.html', {
        'mode': 'create',
        'project': project,
        'action_url': reverse('minutes_create_action', args=[project.id]),
        'cancel_url': reverse('project_detail', args=[project.id]),
        **_form_context(),
    })


@require_POST
@login_required_json
def minutes_create_action(request, project_id):
    """회의록 + 회의 자료(doc_type '0') + 음성파일(doc_type '1') 저장 (JSON 응답)"""
    try:
        project = get_project_or_404(request.user, project_id)
    except Http404:
        return json_error('프로젝트를 찾을 수 없거나 접근 권한이 없습니다.', status=404)

    title, content, audio, documents, errors = _clean_minutes_post(request)
    if errors:
        return json_error('입력값을 확인해 주세요.', errors)

    with transaction.atomic():
        minutes = Minutes.objects.create(
            project=project,
            title=title,
            content=content,
            created_by=request.user,
            updated_by=request.user,
        )
        for doc in documents:
            _save_file(minutes, doc, DOC_TYPE_DOCUMENT, request.user)
        if audio:
            _save_file(minutes, audio, DOC_TYPE_AUDIO, request.user)
            start_minutes_analysis(minutes)  # 커밋 후 백그라운드에서 음성 변환 + 정리 + 업무 추출

    messages.success(request, '회의록이 저장되었습니다.' + (' 음성 분석을 시작합니다.' if audio else ''))  # 이동한 페이지 상단에 표시
    return json_success('회의록이 저장되었습니다.', reverse('minutes_detail', args=[project.id, minutes.id]))


@login_required_page
def minutes_update(request, project_id, minutes_id):
    """회의록 수정 화면 (저장은 minutes_update_action)"""
    project, minutes = get_editable_minutes(request.user, project_id, minutes_id)
    return render(request, 'minutes/minute_form.html', {
        'mode': 'update',
        'project': project,
        'minutes': minutes,
        'audio_files': active_audio_files(minutes),
        'document_files': active_document_files(minutes),
        'action_url': reverse('minutes_update_action', args=[project.id, minutes.id]),
        'cancel_url': reverse('minutes_detail', args=[project.id, minutes.id]),
        **_form_context(),
    })


@require_POST
@login_required_json
def minutes_update_action(request, project_id, minutes_id):
    """
    회의록 수정 (JSON 응답)
    - remove_file_ids 로 넘어온 기존 파일(음성/회의 자료)은 숨김
    - 음성파일: 새 파일을 올리면 기존 음성파일은 모두 교체되고 AI 분석을 다시 한다
    - 회의 자료: 새 파일은 추가 (AI 정리에 반영하려면 상세 화면에서 '다시 분석')
    """
    try:
        project, minutes = get_editable_minutes(request.user, project_id, minutes_id)
    except Http404:
        return json_error('회의록을 찾을 수 없거나 접근 권한이 없습니다.', status=404)
    except PermissionDenied as e:
        return json_error(str(e), status=403)

    remove_ids = {int(v) for v in request.POST.getlist('remove_file_ids') if v.isdigit()}
    current_audio = active_audio_files(minutes)
    kept_documents = active_document_files(minutes).exclude(id__in=remove_ids).count()

    title, content, audio, documents, errors = _clean_minutes_post(request, kept_documents)
    if errors:
        return json_error('입력값을 확인해 주세요.', errors)

    user = request.user
    with transaction.atomic():
        minutes.title = title
        minutes.content = content
        minutes.updated_by = user
        # 필드를 지정해 저장: 백그라운드 분석이 쓰는 ai_status/summary/transcript 를 덮어쓰지 않도록
        minutes.save(update_fields=['title', 'content', 'updated_by', 'updated_at'])

        if remove_ids:
            # 이 회의록의 파일만 (다른 회의록의 파일 id 를 보내도 무시됨)
            _hide_files(MinutesFile.objects.filter(minutes=minutes, use_flag='Y', id__in=remove_ids), user)
        for doc in documents:
            _save_file(minutes, doc, DOC_TYPE_DOCUMENT, user)
        if audio:
            _hide_files(current_audio, user)  # 교체
            _save_file(minutes, audio, DOC_TYPE_AUDIO, user)
            start_minutes_analysis(minutes)  # 새 음성으로 다시 분석 (기존 업무 목록은 교체됨)

    messages.success(request, '회의록이 수정되었습니다.')
    return json_success('회의록이 수정되었습니다.', reverse('minutes_detail', args=[project.id, minutes.id]))


@require_POST
@login_required_json
def minutes_delete_action(request, project_id, minutes_id):
    """회의록 삭제 (JSON 응답). use_flag='N' 으로 숨김 처리 -> 목록/상세/음성파일 접근 불가"""
    try:
        project, minutes = get_editable_minutes(request.user, project_id, minutes_id)
    except Http404:
        return json_error('회의록을 찾을 수 없거나 접근 권한이 없습니다.', status=404)
    except PermissionDenied as e:
        return json_error(str(e), status=403)

    minutes.use_flag = 'N'
    minutes.updated_by = request.user
    minutes.save(update_fields=['use_flag', 'updated_by', 'updated_at'])

    message = f"'{minutes.title}' 회의록이 삭제되었습니다."
    messages.success(request, message)
    return json_success(message, reverse('project_detail', args=[project.id]))


@require_POST
@login_required_json
def minutes_analyze_action(request, project_id, minutes_id):
    """음성파일 AI 분석 다시 실행 (JSON 응답). 기존 업무 목록은 새 결과로 교체된다."""
    try:
        project, minutes = get_editable_minutes(request.user, project_id, minutes_id)
    except Http404:
        return json_error('회의록을 찾을 수 없거나 접근 권한이 없습니다.', status=404)
    except PermissionDenied as e:
        return json_error(str(e), status=403)

    if not active_audio_files(minutes).exists():
        return json_error('분석할 음성파일이 없습니다.')
    if minutes.ai_status in ('W', 'R'):
        return json_error('이미 분석 중입니다. 잠시 후 새로고침해 주세요.', status=409)

    with transaction.atomic():
        start_minutes_analysis(minutes)
    messages.success(request, '음성 분석을 다시 시작했습니다.')
    return json_success('음성 분석을 다시 시작했습니다.', reverse('minutes_detail', args=[project.id, minutes.id]))


@login_required_page
def minutes_detail(request, project_id, minutes_id):
    """회의록 상세 (+ 회의 자료, AI 회의 정리, 업무 목록)"""
    project, minutes = get_minutes_or_404(request.user, project_id, minutes_id)
    audio_files = active_audio_files(minutes)
    tasks = list(Task.objects.filter(minutes=minutes, use_flag='Y').select_related('user').order_by('id'))
    return render(request, 'minutes/minute_detail.html', {
        'project': project,
        'minutes': minutes,
        'audio_files': audio_files,
        'document_files': active_document_files(minutes),
        'has_audio': audio_files.exists(),
        'tasks': tasks,
        'unassigned_count': sum(1 for t in tasks if t.user_id is None),
        'ai_running': minutes.ai_status in ('W', 'R'),
        'can_edit': can_edit_minutes(request.user, project, minutes),  # 수정/삭제/업무 배정 버튼 표시
    })


@login_required_page
def minutes_tasks(request, project_id, minutes_id):
    """
    업무 배정 화면: 회의록 분석으로 만들어진 업무를 프로젝트 참여자에게 배정한다.
    (업무 내용·마감일 수정, 삭제, 직접 추가도 가능) 저장은 minutes_tasks_save_action.
    업무 목록이 만들어진 뒤(분석 완료)에만 들어올 수 있다.
    """
    project, minutes = get_editable_minutes(request.user, project_id, minutes_id)
    tasks = Task.objects.filter(minutes=minutes, use_flag='Y').select_related('user').order_by('id')
    if minutes.ai_status != 'D' and not tasks.exists():
        messages.info(request, '음성파일 분석으로 업무 목록이 만들어진 뒤에 업무를 배정할 수 있습니다.')
        return redirect('minutes_detail', project.id, minutes.id)

    return render(request, 'minutes/minute_tasks.html', {
        'project': project,
        'minutes': minutes,
        'tasks': tasks,
        'members': project_members(project),
        'content_max_length': TASK_CONTENT_MAX_LENGTH,
        'action_url': reverse('minutes_tasks_save_action', args=[project.id, minutes.id]),
        'cancel_url': reverse('minutes_detail', args=[project.id, minutes.id]),
    })


def _clean_task_rows(raw, minutes, member_ids):
    """
    업무 배정 화면에서 보낸 JSON -> (rows, error)
    raw: [{"id": 3 | null, "content": "...", "user_id": 5 | null, "due_date": "YYYY-MM-DD" | "", "deleted": bool}]
    """
    try:
        items = json.loads(raw or '[]')
    except ValueError:
        return None, '업무 목록을 읽지 못했습니다. 새로고침 후 다시 시도해 주세요.'
    if not isinstance(items, list):
        return None, '업무 목록 형식이 올바르지 않습니다.'

    existing_ids = set(Task.objects.filter(minutes=minutes, use_flag='Y').values_list('id', flat=True))
    rows = []
    for no, item in enumerate(items, 1):
        if not isinstance(item, dict):
            return None, '업무 목록 형식이 올바르지 않습니다.'
        task_id = item.get('id')
        if task_id is not None and task_id not in existing_ids:
            return None, '이미 삭제되었거나 다른 회의록의 업무가 있습니다. 새로고침 후 다시 시도해 주세요.'
        if item.get('deleted'):
            if task_id is not None:
                rows.append({'id': task_id, 'deleted': True})
            continue

        content = str(item.get('content') or '').strip()
        if not content:
            return None, f'{no}번째 업무 내용을 입력해 주세요.'
        if len(content) > TASK_CONTENT_MAX_LENGTH:
            return None, f'{no}번째 업무 내용은 {TASK_CONTENT_MAX_LENGTH}자 이하로 입력해 주세요.'
        user_id = item.get('user_id') or None
        if user_id is not None and user_id not in member_ids:
            return None, f'{no}번째 업무의 담당자는 프로젝트 참여자 중에서 골라 주세요.'
        due_raw = str(item.get('due_date') or '').strip()
        due_at = parse_due_date(due_raw) if due_raw else None
        if due_raw and due_at is None:
            return None, f'{no}번째 업무의 마감일 형식이 올바르지 않습니다.'
        rows.append({'id': task_id, 'deleted': False, 'content': content, 'user_id': user_id, 'due_at': due_at})
    return rows, None


@require_POST
@login_required_json
def minutes_tasks_save_action(request, project_id, minutes_id):
    """업무 배정 저장 (JSON 응답). 삭제는 use_flag='N'"""
    try:
        project, minutes = get_editable_minutes(request.user, project_id, minutes_id)
    except Http404:
        return json_error('회의록을 찾을 수 없거나 접근 권한이 없습니다.', status=404)
    except PermissionDenied as e:
        return json_error(str(e), status=403)
    if minutes.ai_status in ('W', 'R'):
        return json_error('AI 분석 중에는 업무를 저장할 수 없습니다. 분석이 끝나면 업무 목록이 새로 만들어집니다.', status=409)

    member_ids = {u.id for u in project_members(project)}
    rows, error = _clean_task_rows(request.POST.get('tasks'), minutes, member_ids)
    if error:
        return json_error(error)

    user = request.user
    now = timezone.now()
    with transaction.atomic():
        for row in rows:
            if row['deleted']:
                Task.objects.filter(pk=row['id'], minutes=minutes).update(use_flag='N', updated_by=user, updated_at=now)
            elif row['id'] is None:
                Task.objects.create(minutes=minutes, user_id=row['user_id'], content=row['content'],
                                    due_at=row['due_at'], complete_flag='N', created_by=user, updated_by=user)
            else:
                Task.objects.filter(pk=row['id'], minutes=minutes).update(
                    user_id=row['user_id'], content=row['content'], due_at=row['due_at'],
                    updated_by=user, updated_at=now,
                )

    unassigned = Task.objects.filter(minutes=minutes, use_flag='Y', user__isnull=True).count()
    message = '업무 배정을 저장했습니다.' + (f' 담당자가 없는 업무가 {unassigned}건 남아 있습니다.' if unassigned else '')
    messages.success(request, message)
    return json_success(message, reverse('minutes_detail', args=[project.id, minutes.id]))


@login_required_page
def minutes_file(request, project_id, minutes_id, file_id):
    """
    첨부파일(회의 자료/음성) 재생·다운로드.
    /media/ 를 직접 공개하지 않고, 프로젝트 참여자인지 확인한 뒤에만 파일을 내려준다.
    """
    project = get_project_or_404(request.user, project_id)
    file = get_object_or_404(
        MinutesFile,
        pk=file_id, minutes_id=minutes_id, minutes__project=project, minutes__use_flag='Y', use_flag='Y',
    )
    return file_response(file, download=request.GET.get('download') == '1')
