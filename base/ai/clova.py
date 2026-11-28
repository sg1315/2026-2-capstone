"""
Naver CLOVA Speech 장문 인식 (로컬 파일 업로드, sync)
문서: https://api.ncloud-docs.com/docs/ai-application-service-clovaspeech-longsentence-local
"""
import json

import requests
from django.conf import settings


class SpeechError(Exception):
    """음성 인식 실패 (화면에 그대로 보여줄 수 있는 메시지)"""


def _format_ms(ms):
    sec = int(ms or 0) // 1000
    return f'{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}' if sec >= 3600 else f'{sec // 60:02d}:{sec % 60:02d}'


def transcribe(file_field, filename):
    """
    FileField 의 음성파일을 텍스트로 변환한다.
    반환: '[00:12] A: 안녕하세요\\n[00:15] B: ...' 처럼 시간·화자가 붙은 줄 단위 텍스트
    """
    invoke_url = settings.CLOVA_SPEECH_INVOKE_URL
    secret_key = settings.CLOVA_SPEECH_SECRET_KEY
    if not invoke_url or not secret_key:
        raise SpeechError('CLOVA Speech 설정(CLOVA_SPEECH_INVOKE_URL, CLOVA_SPEECH_SECRET_KEY)이 없습니다.')

    params = {
        'language': 'ko-KR',
        'completion': 'sync',          # 결과를 응답으로 바로 받는다 (callback 서버 불필요)
        'diarization': {'enable': True},  # 화자 구분
        'wordAlignment': False,
        'fullText': True,
    }
    try:
        with file_field.open('rb') as media:
            response = requests.post(
                invoke_url.rstrip('/') + '/recognizer/upload',
                headers={'X-CLOVASPEECH-API-KEY': secret_key},
                files={'media': (filename, media)},
                data={'params': json.dumps(params)},
                timeout=(10, 1800),  # 연결 10초, 변환 대기 최대 30분
            )
    except requests.RequestException as e:
        raise SpeechError(f'CLOVA Speech 서버에 연결하지 못했습니다. ({e.__class__.__name__})') from e

    try:
        data = response.json()
    except ValueError:
        raise SpeechError(f'CLOVA Speech 응답을 읽지 못했습니다. (HTTP {response.status_code})')

    if response.status_code != 200 or data.get('result') != 'COMPLETED':
        raise SpeechError(f"음성 인식에 실패했습니다. ({data.get('result') or response.status_code}: {data.get('message', '')})")

    lines = []
    for seg in data.get('segments') or []:
        text = (seg.get('text') or '').strip()
        if not text:
            continue
        speaker = (seg.get('speaker') or {}).get('name') or (seg.get('speaker') or {}).get('label') or '?'
        lines.append(f"[{_format_ms(seg.get('start'))}] {speaker}: {text}")

    transcript = '\n'.join(lines) or (data.get('text') or '').strip()
    if not transcript:
        raise SpeechError('음성에서 인식된 말이 없습니다.')
    return transcript
