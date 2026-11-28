"""
회의록 AI 분석 흐름
  음성파일(doc_type '1') -> CLOVA Speech 로 텍스트 변환
  + 작성자 메모(Minutes.content) + 참고 문서(회의 자료 / 프로젝트 첨부파일의 doc_type '0')
  -> Claude 로 회의 정리 + 업무 추출
  -> Minutes.transcript / summary 저장, Task 생성

요청을 붙잡지 않도록 백그라운드 스레드에서 돌린다 (start_minutes_analysis).
진행 상태는 Minutes.ai_status 로 확인한다: W(대기) -> R(분석 중) -> D(완료) / F(실패)
주의: 개발 서버가 코드 변경으로 재시작되면 진행 중이던 분석은 끊긴다 -> 상세 화면에서 '다시 분석'
"""
import datetime
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from base.models import Minutes, MinutesFile, ProjectFile, Task, UserProject
from .claude import AnalysisError, analyze_minutes
from .clova import SpeechError, transcribe
from .documents import collect_documents

logger = logging.getLogger(__name__)

DOC_TYPE_DOCUMENT = '0'
DOC_TYPE_AUDIO = '1'
WEEKDAYS = '월화수목금토일'


def start_minutes_analysis(minutes):
    """
    분석 대기 상태로 바꾸고, 현재 트랜잭션이 커밋된 뒤 백그라운드에서 분석을 시작한다.
    (커밋 전에 스레드가 돌면 방금 저장한 회의록/음성파일을 못 읽기 때문)
    """
    minutes.ai_status = 'W'
    minutes.ai_message = None
    minutes.save(update_fields=['ai_status', 'ai_message'])
    transaction.on_commit(
        lambda: threading.Thread(target=_run_in_thread, args=(minutes.id,), daemon=True).start()
    )


def _run_in_thread(minutes_id):
    close_old_connections()
    try:
        run_minutes_analysis(minutes_id)
    finally:
        connection.close()  # 스레드마다 DB 연결이 따로 열리므로 직접 닫는다


def _set_status(minutes, status, message=None):
    minutes.ai_status = status
    minutes.ai_message = (message or '')[:1000] or None
    minutes.save(update_fields=['ai_status', 'ai_message'])


def parse_due_date(value):
    """'YYYY-MM-DD' -> 그날 23:59 (잘못된 값이면 None)"""
    try:
        day = datetime.date.fromisoformat(value or '')
    except ValueError:
        return None
    due = datetime.datetime.combine(day, datetime.time(23, 59))
    return timezone.make_aware(due) if settings.USE_TZ else due


def _reference_files(minutes):
    """
    프로젝트 개요(계획서 등, 프로젝트 전체의 기반 문서)를 먼저, 그다음 이 회의의 자료.
    분량 상한(documents.MAX_CHARS_TOTAL)을 넘으면 뒤쪽부터 빠지므로 기반 문서가 항상 들어간다.
    """
    project = ProjectFile.objects.filter(project=minutes.project, doc_type=DOC_TYPE_DOCUMENT, use_flag='Y').order_by('id')
    meeting = MinutesFile.objects.filter(minutes=minutes, doc_type=DOC_TYPE_DOCUMENT, use_flag='Y').order_by('id')
    return ([('프로젝트 개요', f.path, f.name) for f in project if f.path]
            + [('회의 자료', f.path, f.name) for f in meeting if f.path])


def run_minutes_analysis(minutes_id):
    minutes = Minutes.objects.select_related('project', 'created_by').get(pk=minutes_id)
    audio = (MinutesFile.objects
             .filter(minutes=minutes, doc_type=DOC_TYPE_AUDIO, use_flag='Y')
             .order_by('-id').first())
    if not audio or not audio.path:
        _set_status(minutes, 'N')
        return

    _set_status(minutes, 'R')
    try:
        transcript = transcribe(audio.path, audio.name or 'audio')
        minutes.transcript = transcript
        minutes.save(update_fields=['transcript'])

        members = [
            {'id': up.user_id, 'name': up.user.name, 'username': up.user.username}
            for up in UserProject.objects.filter(project=minutes.project, use_flag='Y').select_related('user')
        ]
        documents, skipped = collect_documents(_reference_files(minutes))
        meeting_day = timezone.localtime(minutes.created_at).date()
        analysis = analyze_minutes(
            project_title=minutes.project.title,
            meeting_title=minutes.title,
            meeting_date=f'{meeting_day:%Y-%m-%d} ({WEEKDAYS[meeting_day.weekday()]})',
            members=members,
            memo=minutes.content,
            transcript=transcript,
            documents=documents,
        )
    except (SpeechError, AnalysisError) as e:
        _set_status(minutes, 'F', str(e))
        return
    except Exception:
        logger.exception('회의록 AI 분석 실패 (minutes_id=%s)', minutes_id)
        _set_status(minutes, 'F', '분석 중 알 수 없는 오류가 발생했습니다.')
        return

    member_ids = {m['id'] for m in members}
    author = minutes.created_by
    with transaction.atomic():
        # 다시 분석하면 이전에 만든 업무는 숨기고 새 결과로 교체
        Task.objects.filter(minutes=minutes, use_flag='Y').update(
            use_flag='N', updated_by=author, updated_at=timezone.now()
        )
        tasks = []
        for item in analysis.tasks:
            content = item.content.strip()
            if not content:
                continue
            assignee_id = item.assignee_id if item.assignee_id in member_ids else None  # 목록 밖 id 는 버린다
            if assignee_id is None and item.assignee_hint.strip():
                content += f' (담당 추정: {item.assignee_hint.strip()})'
            tasks.append(Task(
                minutes=minutes,
                user_id=assignee_id,
                content=content,
                due_at=parse_due_date(item.due_date),
                complete_flag='N',
                created_by=author,
                updated_by=author,
            ))
        Task.objects.bulk_create(tasks)

        minutes.summary = analysis.summary.strip()
        minutes.ai_status = 'D'
        # 완료 시에는 참고하지 못한 문서를 안내 문구로 남긴다
        minutes.ai_message = ('참고하지 못한 문서: ' + ', '.join(skipped))[:1000] if skipped else None
        minutes.save(update_fields=['summary', 'ai_status', 'ai_message'])
