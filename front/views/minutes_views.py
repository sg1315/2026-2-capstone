from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from base.models import Minutes, MinutesFile
from .common import json_error, json_success, login_required_json, login_required_page
from .files import AUDIO_EXTENSIONS, AUDIO_MAX_SIZE, extensions_attr, file_response, validate_upload
from .project_views import get_project_or_404

DOC_TYPE_AUDIO = '1'  # MinutesFile.DOC_TYPE_CHOICES: '1' = 음성파일


def get_minutes_or_404(user, project_id, minutes_id):
    """참여 중인 프로젝트의 (삭제되지 않은) 회의록. 아니면 Http404 -> (project, minutes)"""
    project = get_project_or_404(user, project_id)
    minutes = get_object_or_404(
        Minutes.objects.select_related('created_by'),
        pk=minutes_id, project=project, use_flag='Y',
    )
    return project, minutes


def can_edit_minutes(user, project, minutes):
    """회의록 수정·삭제 권한: 회의록 작성자 또는 프로젝트를 만든 사람"""
    return user.id in (minutes.created_by_id, project.created_by_id)


def get_editable_minutes(user, project_id, minutes_id):
    """수정/삭제용. 접근 불가면 Http404, 볼 수는 있지만 권한이 없으면 PermissionDenied"""
    project, minutes = get_minutes_or_404(user, project_id, minutes_id)
    if not can_edit_minutes(user, project, minutes):
        raise PermissionDenied('회의록 작성자나 프로젝트를 만든 사람만 수정하거나 삭제할 수 있습니다.')
    return project, minutes


def active_audio_files(minutes):
    return MinutesFile.objects.filter(minutes=minutes, doc_type=DOC_TYPE_AUDIO, use_flag='Y').order_by('id')


def _form_context():
    """생성/수정 화면 공통: JS 검사에 쓰는 제한값"""
    return {
        'audio_max_size': AUDIO_MAX_SIZE,
        'audio_extensions': extensions_attr(AUDIO_EXTENSIONS),
    }


def _clean_minutes_post(request):
    """생성/수정 공통 입력값 검증 -> (title, content, audio, errors)"""
    title = request.POST.get('title', '').strip()
    content = request.POST.get('content', '').strip()
    audio = request.FILES.get('audio')

    errors = {}
    if not title:
        errors['title'] = '회의록 제목을 입력해 주세요.'
    elif len(title) > 2000:
        errors['title'] = '회의록 제목은 2000자 이하로 입력해 주세요.'
    if not content:
        errors['content'] = '회의 내용을 입력해 주세요.'
    if audio:
        audio_error = validate_upload(audio, AUDIO_EXTENSIONS, AUDIO_MAX_SIZE, '음성파일')
        if audio_error:
            errors['audio'] = audio_error
    return title, content, audio, errors


def _save_audio(minutes, audio, user):
    """저장 경로(upload_to)가 minutes.id 를 쓰므로 회의록이 저장된 뒤에 호출"""
    MinutesFile.objects.create(
        minutes=minutes,
        path=audio,
        name=audio.name,
        type=audio.content_type,
        size=audio.size,
        doc_type=DOC_TYPE_AUDIO,
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
    """회의록 + 음성파일 저장 (JSON 응답)"""
    try:
        project = get_project_or_404(request.user, project_id)
    except Http404:
        return json_error('프로젝트를 찾을 수 없거나 접근 권한이 없습니다.', status=404)

    title, content, audio, errors = _clean_minutes_post(request)
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
        if audio:
            _save_audio(minutes, audio, request.user)

    messages.success(request, '회의록이 저장되었습니다.')  # 이동한 페이지 상단에 표시
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
        'action_url': reverse('minutes_update_action', args=[project.id, minutes.id]),
        'cancel_url': reverse('minutes_detail', args=[project.id, minutes.id]),
        **_form_context(),
    })


@require_POST
@login_required_json
def minutes_update_action(request, project_id, minutes_id):
    """
    회의록 수정 (JSON 응답)
    - 음성파일: remove_file_ids 로 넘어온 기존 파일은 숨김, 새 파일을 올리면 기존 음성파일은 모두 교체
    """
    try:
        project, minutes = get_editable_minutes(request.user, project_id, minutes_id)
    except Http404:
        return json_error('회의록을 찾을 수 없거나 접근 권한이 없습니다.', status=404)
    except PermissionDenied as e:
        return json_error(str(e), status=403)

    title, content, audio, errors = _clean_minutes_post(request)
    if errors:
        return json_error('입력값을 확인해 주세요.', errors)

    current_audio = active_audio_files(minutes)
    remove_ids = {int(v) for v in request.POST.getlist('remove_file_ids') if v.isdigit()}

    user = request.user
    with transaction.atomic():
        minutes.title = title
        minutes.content = content
        minutes.updated_by = user
        minutes.save()

        if audio:
            _hide_files(current_audio, user)  # 교체
            _save_audio(minutes, audio, user)
        elif remove_ids:
            _hide_files(current_audio.filter(id__in=remove_ids), user)  # 이 회의록의 파일만

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


@login_required_page
def minutes_detail(request, project_id, minutes_id):
    """회의록 상세"""
    project, minutes = get_minutes_or_404(request.user, project_id, minutes_id)
    return render(request, 'minutes/minute_detail.html', {
        'project': project,
        'minutes': minutes,
        'audio_files': active_audio_files(minutes),
        'can_edit': can_edit_minutes(request.user, project, minutes),  # 수정/삭제 버튼 표시
    })


@login_required_page
def minutes_file(request, project_id, minutes_id, file_id):
    """
    첨부파일 재생/다운로드.
    /media/ 를 직접 공개하지 않고, 프로젝트 참여자인지 확인한 뒤에만 파일을 내려준다.
    """
    project = get_project_or_404(request.user, project_id)
    file = get_object_or_404(
        MinutesFile,
        pk=file_id, minutes_id=minutes_id, minutes__project=project, minutes__use_flag='Y', use_flag='Y',
    )
    return file_response(file, download=request.GET.get('download') == '1')
