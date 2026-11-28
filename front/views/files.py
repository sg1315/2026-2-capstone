"""첨부파일 공통: 형식/용량 검증, 권한 확인 후 파일 응답"""
import mimetypes
import os

from django.http import FileResponse, Http404

MB = 1024 * 1024

# 회의록 음성파일
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.webm', '.ogg', '.aac', '.flac'}
AUDIO_MAX_SIZE = 200 * MB

# 회의 자료 (회의에 사용한 문서). AI 가 읽을 수 있는 형식은 base/ai/documents.py 참고
DOCUMENT_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.hwp', '.hwpx', '.txt', '.md', '.csv',
}
MINUTES_DOC_MAX_SIZE = 50 * MB
MINUTES_DOC_MAX_COUNT = 5

# 프로젝트 첨부파일 (문서/이미지/압축 + 음성)
PROJECT_FILE_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.hwp', '.hwpx',
    '.txt', '.md', '.csv', '.png', '.jpg', '.jpeg', '.gif', '.zip',
} | AUDIO_EXTENSIONS
PROJECT_FILE_MAX_SIZE = 50 * MB
PROJECT_FILE_MAX_COUNT = 5


def file_ext(name):
    return os.path.splitext(name)[1].lower()


def validate_upload(file, extensions, max_size, label='파일'):
    """형식/용량 검증. 문제가 있으면 오류 메시지, 없으면 None"""
    if file_ext(file.name) not in extensions:
        return f"{label}은(는) {', '.join(sorted(e[1:] for e in extensions))} 형식만 첨부할 수 있습니다. ({file.name})"
    if file.size > max_size:
        return f'{label}은(는) {max_size // MB}MB 이하만 첨부할 수 있습니다. ({file.name})'
    return None


def extensions_attr(extensions):
    """<input accept> / data 속성용 '.pdf,.png,...' 문자열"""
    return ','.join(sorted(extensions))


def file_response(file_obj, download=False):
    """
    MinutesFile / ProjectFile 의 실제 파일을 내려준다. (권한 확인은 호출하는 view 에서)
    /media/ 를 공개하지 않고 이 함수를 거쳐서만 파일에 접근한다.
    """
    if not file_obj.path:
        raise Http404('파일이 없습니다.')
    try:
        handle = file_obj.path.open('rb')
    except FileNotFoundError:
        raise Http404('파일을 찾을 수 없습니다.')

    content_type = file_obj.type or mimetypes.guess_type(file_obj.name or '')[0] or 'application/octet-stream'
    return FileResponse(handle, content_type=content_type, as_attachment=download, filename=file_obj.name)
