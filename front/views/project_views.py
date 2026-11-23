import re
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from base.models import Minutes, Project, ProjectFile, ProjectHashtag, User, UserProject
from .common import is_ajax, json_error, json_success, login_required_json, login_required_page
from .files import (
    AUDIO_EXTENSIONS, PROJECT_FILE_EXTENSIONS, PROJECT_FILE_MAX_COUNT, PROJECT_FILE_MAX_SIZE,
    extensions_attr, file_ext, file_response, validate_upload,
)

# 해시태그 규칙 (project_form.html 의 JS 검사와 같은 값)
HASHTAG_MAX_COUNT = 3
HASHTAG_MAX_LENGTH = 20
HASHTAG_PATTERN = re.compile(r'^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ_]+$')

# 참여자 (생성자 제외) 최대 인원
MEMBER_MAX_COUNT = 20

# ProjectFile.DOC_TYPE_CHOICES: '0' = 개요(일반 문서), '1' = 음성파일
DOC_TYPE_DOCUMENT = '0'
DOC_TYPE_AUDIO = '1'


def get_user_projects(user):
    """로그인 사용자가 참여 중인 프로젝트 (삭제되지 않은 것만)"""
    project_ids = UserProject.objects.filter(user=user, use_flag='Y').values_list('project_id', flat=True)
    return Project.objects.filter(id__in=project_ids).exclude(use_flag=False)


def get_project_or_404(user, project_id):
    """참여 중인 프로젝트가 아니면 404 (다른 사람 프로젝트 접근 차단)"""
    try:
        return get_user_projects(user).get(pk=project_id)
    except Project.DoesNotExist:
        raise Http404('프로젝트를 찾을 수 없습니다.')


def active_hashtags_prefetch():
    """project.active_hashtags 로 사용할 해시태그 목록 (사용 중인 것만, 입력 순서대로)"""
    return Prefetch('hashtags', queryset=ProjectHashtag.objects.filter(use_flag='Y').order_by('id'),
                    to_attr='active_hashtags')


def parse_member_ids(request, owner):
    """
    폼의 member_ids(hidden input 여러 개) -> (활성 사용자 목록, 오류메시지 또는 None)
    생성자 본인은 항상 참여자이므로 목록에서 뺀다.
    """
    ids = []
    for value in request.POST.getlist('member_ids'):
        if value.isdigit() and int(value) != owner.id and int(value) not in ids:
            ids.append(int(value))
    if len(ids) > MEMBER_MAX_COUNT:
        return [], f'참여자는 최대 {MEMBER_MAX_COUNT}명까지 추가할 수 있습니다.'
    users = list(User.objects.filter(id__in=ids, is_active=True))
    if len(users) != len(ids):
        return [], '존재하지 않거나 사용할 수 없는 사용자가 포함되어 있습니다.'
    return users, None


def sync_members(project, users, actor):
    """
    프로젝트 참여자를 users(+생성자)로 맞춘다.
    빠진 사람은 use_flag='N', 예전에 빠졌던 사람을 다시 넣으면 기존 행을 되살린다.
    """
    wanted = {u.id for u in users}
    wanted.add(project.created_by_id)
    rows = {row.user_id: row for row in UserProject.objects.filter(project=project)}

    for user_id, row in rows.items():
        flag = 'Y' if user_id in wanted else 'N'
        if row.use_flag != flag:
            row.use_flag = flag
            row.updated_by = actor
            row.save(update_fields=['use_flag', 'updated_by', 'updated_at'])

    UserProject.objects.bulk_create([
        UserProject(user_id=user_id, project=project, created_by=actor, updated_by=actor)
        for user_id in wanted if user_id not in rows
    ])


def member_chips(project):
    """수정 화면에 미리 그릴 참여자(생성자 제외)"""
    return [
        row.user for row in UserProject.objects.filter(project=project, use_flag='Y')
        .exclude(user_id=project.created_by_id).select_related('user').order_by('id')
    ]


def parse_hashtags(raw):
    """
    '#기획, 디자인 #AI' -> (['기획', '디자인', 'AI'], 오류메시지 또는 None)
    쉼표/공백으로 구분, 앞의 '#' 제거, 대소문자 무시 중복 제거
    """
    tags, seen = [], set()
    for token in re.split(r'[\s,]+', raw or ''):
        tag = token.lstrip('#').strip()
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        tags.append(tag)

    if len(tags) > HASHTAG_MAX_COUNT:
        return tags, f'해시태그는 최대 {HASHTAG_MAX_COUNT}개까지 입력할 수 있습니다.'
    for tag in tags:
        if len(tag) > HASHTAG_MAX_LENGTH:
            return tags, f'해시태그는 {HASHTAG_MAX_LENGTH}자 이하로 입력해 주세요. (#{tag})'
        if not HASHTAG_PATTERN.match(tag):
            return tags, f'해시태그는 한글, 영문, 숫자, _ 만 사용할 수 있습니다. (#{tag})'
    return tags, None


@login_required_page
def project_list(request):
    """
    프로젝트 목록
    - tab=mine   : 내가 만든 프로젝트 (기본)
    - tab=shared : 다른 사람이 만들고 나를 참여자로 추가한 프로젝트
    - q          : 프로젝트명 또는 해시태그 검색 ('#'으로 시작하면 해시태그만 검색)
    JS(검색/탭 전환) 요청이면 목록 부분(_project_items.html)만 돌려준다.
    """
    tab = request.GET.get('tab', 'mine')
    q = request.GET.get('q', '').strip()

    projects = get_user_projects(request.user)
    if tab == 'shared':
        projects = projects.exclude(created_by=request.user)
    else:
        tab = 'mine'
        projects = projects.filter(created_by=request.user)

    keyword = q.lstrip('#').strip()
    if keyword:
        # 해시태그는 서브쿼리로 찾는다 (JOIN 하면 프로젝트가 중복되고 회의록 수가 부풀려짐)
        tagged_ids = ProjectHashtag.objects.filter(
            name__icontains=keyword, use_flag='Y'
        ).values('project_id')
        if q.startswith('#'):
            projects = projects.filter(id__in=tagged_ids)
        else:
            projects = projects.filter(Q(title__icontains=keyword) | Q(id__in=tagged_ids))

    # Minutes.project 는 related_name 이 없어 역참조 이름이 'minutes'
    projects = projects.annotate(
        minutes_count=Count('minutes', filter=Q(minutes__use_flag='Y'))
    ).prefetch_related(active_hashtags_prefetch()).order_by('-created_at')

    context = {'projects': projects, 'tab': tab, 'q': q}
    if is_ajax(request):
        return render(request, 'project/_project_items.html', context)
    return render(request, 'project/project_list.html', context)


def get_owned_project(user, project_id):
    """
    수정/삭제용. 참여 중이 아니면 Http404, 참여자지만 생성자가 아니면 PermissionDenied.
    (프로젝트 수정·삭제는 생성자만 가능)
    """
    project = get_project_or_404(user, project_id)
    if project.created_by_id != user.id:
        raise PermissionDenied('프로젝트를 만든 사람만 수정하거나 삭제할 수 있습니다.')
    return project


def _form_limits():
    """생성/수정 화면 공통: JS 검사에 쓰는 제한값"""
    return {
        'hashtag_max_count': HASHTAG_MAX_COUNT,
        'hashtag_max_length': HASHTAG_MAX_LENGTH,
        'file_extensions': extensions_attr(PROJECT_FILE_EXTENSIONS),
        'file_max_size': PROJECT_FILE_MAX_SIZE,
        'file_max_count': PROJECT_FILE_MAX_COUNT,
        'member_max_count': MEMBER_MAX_COUNT,
    }


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _clean_project_post(request, owner, kept_file_count=0):
    """
    생성/수정 공통 입력값 정리·검증
    kept_file_count: (수정 시) 삭제하지 않고 남길 기존 첨부파일 수 -> 새 파일과 합쳐 최대 개수 검사
    -> (cleaned dict, errors dict)
    """
    data = {k: request.POST.get(k, '').strip() for k in ('title', 'content', 'start_at', 'end_at')}
    start_at = _parse_date(data['start_at'])
    end_at = _parse_date(data['end_at'])
    hashtags, hashtag_error = parse_hashtags(request.POST.get('hashtags', ''))
    files = request.FILES.getlist('files')
    members, member_error = parse_member_ids(request, owner)

    errors = {}
    if member_error:
        errors['member_ids'] = member_error
    if not data['title']:
        errors['title'] = '프로젝트명을 입력해 주세요.'
    elif len(data['title']) > 2000:
        errors['title'] = '프로젝트명은 2000자 이하로 입력해 주세요.'
    if data['start_at'] and not start_at:
        errors['start_at'] = '날짜 형식이 올바르지 않습니다.'
    if data['end_at'] and not end_at:
        errors['end_at'] = '날짜 형식이 올바르지 않습니다.'
    if start_at and end_at and end_at < start_at:
        errors['end_at'] = '종료일은 시작일 이후여야 합니다.'
    if hashtag_error:
        errors['hashtags'] = hashtag_error
    if kept_file_count + len(files) > PROJECT_FILE_MAX_COUNT:
        errors['files'] = f'첨부파일은 기존 파일을 포함해 최대 {PROJECT_FILE_MAX_COUNT}개까지 올릴 수 있습니다.'
    else:
        for f in files:
            file_error = validate_upload(f, PROJECT_FILE_EXTENSIONS, PROJECT_FILE_MAX_SIZE, '첨부파일')
            if file_error:
                errors['files'] = file_error
                break

    cleaned = {
        'title': data['title'],
        'content': data['content'] or None,
        'start_at': start_at,
        'end_at': end_at,
        'hashtags': hashtags,
        'files': files,
        'members': members,
    }
    return cleaned, errors


def _save_project_files(project, files, user):
    """저장 경로(upload_to)가 project.id 를 쓰므로 프로젝트가 저장된 뒤에 호출"""
    for f in files:
        ProjectFile.objects.create(
            project=project,
            path=f,
            name=f.name,
            type=f.content_type,
            size=f.size,
            doc_type=DOC_TYPE_AUDIO if file_ext(f.name) in AUDIO_EXTENSIONS else DOC_TYPE_DOCUMENT,
            created_by=user,
            updated_by=user,
        )


@login_required_page
def project_create(request):
    """프로젝트 생성 화면 (저장은 project_create_action)"""
    return render(request, 'project/project_form.html', {
        'mode': 'create',
        'action_url': reverse('project_create_action'),
        'cancel_url': reverse('project_list'),
        **_form_limits(),
    })


@require_POST
@login_required_json
def project_create_action(request):
    """프로젝트 + 해시태그 + 첨부파일 저장 (JSON 응답)"""
    cleaned, errors = _clean_project_post(request, request.user)
    if errors:
        return json_error('입력값을 확인해 주세요.', errors)

    user = request.user
    with transaction.atomic():
        project = Project.objects.create(
            title=cleaned['title'],
            content=cleaned['content'],
            start_at=cleaned['start_at'],
            end_at=cleaned['end_at'],
            created_by=user,
            updated_by=user,
            use_flag=True,
        )
        # 생성자 + 선택한 참여자 등록
        sync_members(project, cleaned['members'], user)
        ProjectHashtag.objects.bulk_create([
            ProjectHashtag(project=project, name=tag, created_by=user, updated_by=user)
            for tag in cleaned['hashtags']
        ])
        _save_project_files(project, cleaned['files'], user)

    message = f"'{project.title}' 프로젝트가 생성되었습니다."
    messages.success(request, message)  # 이동한 페이지 상단에 표시
    return json_success(message, reverse('project_detail', args=[project.id]))


@login_required_page
def project_update(request, project_id):
    """프로젝트 수정 화면 (저장은 project_update_action). 생성자만 가능"""
    project = get_owned_project(request.user, project_id)
    hashtags = ProjectHashtag.objects.filter(project=project, use_flag='Y').order_by('id')
    return render(request, 'project/project_form.html', {
        'mode': 'update',
        'project': project,
        'hashtags_value': ' '.join(f'#{t.name}' for t in hashtags),
        'project_files': ProjectFile.objects.filter(project=project, use_flag='Y').order_by('id'),
        'members': member_chips(project),
        'action_url': reverse('project_update_action', args=[project.id]),
        'cancel_url': reverse('project_detail', args=[project.id]),
        **_form_limits(),
    })


@require_POST
@login_required_json
def project_update_action(request, project_id):
    """
    프로젝트 수정 (JSON 응답)
    - 해시태그: 입력값으로 교체 (빠진 태그는 use_flag='N', 새 태그 추가)
    - 첨부파일: remove_file_ids 로 넘어온 기존 파일은 use_flag='N', 새 파일 추가
    - 참여자: member_ids 로 교체 (생성자는 항상 유지)
    """
    try:
        project = get_owned_project(request.user, project_id)
    except Http404:
        return json_error('프로젝트를 찾을 수 없거나 접근 권한이 없습니다.', status=404)
    except PermissionDenied as e:
        return json_error(str(e), status=403)

    current_files = ProjectFile.objects.filter(project=project, use_flag='Y')
    remove_ids = {int(v) for v in request.POST.getlist('remove_file_ids') if v.isdigit()}
    remove_ids &= set(current_files.values_list('id', flat=True))  # 이 프로젝트의 파일만
    kept_count = current_files.count() - len(remove_ids)

    cleaned, errors = _clean_project_post(request, request.user, kept_file_count=kept_count)
    if errors:
        return json_error('입력값을 확인해 주세요.', errors)

    user = request.user
    with transaction.atomic():
        project.title = cleaned['title']
        project.content = cleaned['content']
        project.start_at = cleaned['start_at']
        project.end_at = cleaned['end_at']
        project.updated_by = user
        project.save()

        # 해시태그 교체 (대소문자 무시 비교, 그대로 남는 태그는 건드리지 않음)
        new_tags = {t.lower(): t for t in cleaned['hashtags']}
        for tag in ProjectHashtag.objects.filter(project=project, use_flag='Y'):
            if tag.name.lower() in new_tags:
                new_tags.pop(tag.name.lower())
            else:
                tag.use_flag = 'N'
                tag.updated_by = user
                tag.save(update_fields=['use_flag', 'updated_by', 'updated_at'])
        ProjectHashtag.objects.bulk_create([
            ProjectHashtag(project=project, name=name, created_by=user, updated_by=user)
            for name in new_tags.values()
        ])

        sync_members(project, cleaned['members'], user)

        for f in current_files.filter(id__in=remove_ids):
            f.use_flag = 'N'
            f.updated_by = user
            f.save(update_fields=['use_flag', 'updated_by', 'updated_at'])
        _save_project_files(project, cleaned['files'], user)

    message = '프로젝트가 수정되었습니다.'
    messages.success(request, message)
    return json_success(message, reverse('project_detail', args=[project.id]))


@require_POST
@login_required_json
def project_delete_action(request, project_id):
    """
    프로젝트 삭제 (JSON 응답). 생성자만 가능.
    다른 데이터와 같이 use_flag 로 숨김 처리 -> 목록/상세/회의록/첨부파일 모두 접근 불가.
    """
    try:
        project = get_owned_project(request.user, project_id)
    except Http404:
        return json_error('프로젝트를 찾을 수 없거나 접근 권한이 없습니다.', status=404)
    except PermissionDenied as e:
        return json_error(str(e), status=403)

    project.use_flag = False
    project.updated_by = request.user
    project.save(update_fields=['use_flag', 'updated_by', 'updated_at'])

    message = f"'{project.title}' 프로젝트가 삭제되었습니다."
    messages.success(request, message)
    return json_success(message, reverse('project_list'))


@login_required_page
def project_detail(request, project_id):
    """
    프로젝트 상세 = 프로젝트 정보(해시태그, 첨부파일) + 회의록 목록
    JS(검색) 요청이면 회의록 목록 부분(_minute_items.html)만 돌려준다.
    """
    project = get_project_or_404(request.user, project_id)
    q = request.GET.get('q', '').strip()

    minutes_list = Minutes.objects.filter(project=project, use_flag='Y')
    if q:
        minutes_list = minutes_list.filter(Q(title__icontains=q) | Q(content__icontains=q))
    minutes_list = minutes_list.select_related('created_by').annotate(
        # MinutesFile.minutes 역참조 이름은 'minutesfile', doc_type '1' = 음성파일
        audio_count=Count('minutesfile', filter=Q(minutesfile__doc_type='1', minutesfile__use_flag='Y'))
    ).order_by('-created_at')

    context = {'project': project, 'minutes_list': minutes_list, 'q': q}
    if is_ajax(request):
        return render(request, 'minutes/_minute_items.html', context)

    context.update({
        'members': UserProject.objects.filter(project=project, use_flag='Y').select_related('user'),
        'minutes_total': Minutes.objects.filter(project=project, use_flag='Y').count(),
        'hashtags': ProjectHashtag.objects.filter(project=project, use_flag='Y').order_by('id'),
        'project_files': ProjectFile.objects.filter(project=project, use_flag='Y').order_by('id'),
        'is_owner': project.created_by_id == request.user.id,  # 수정/삭제 버튼 표시
    })
    return render(request, 'minutes/minute_list.html', context)


@login_required_page
def project_file(request, project_id, file_id):
    """프로젝트 첨부파일 열기/다운로드 (프로젝트 참여자만)"""
    project = get_project_or_404(request.user, project_id)
    file = get_object_or_404(ProjectFile, pk=file_id, project=project, use_flag='Y')
    return file_response(file, download=request.GET.get('download') == '1')
