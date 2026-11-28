"""Claude API 로 회의 정리 + 업무 추출 (structured outputs)"""
from typing import List, Optional

import anthropic
from django.conf import settings
from pydantic import BaseModel

from .prompts import MINUTES_SYSTEM_PROMPT, build_minutes_user_prompt


class AnalysisError(Exception):
    """AI 분석 실패 (화면에 그대로 보여줄 수 있는 메시지)"""


class ExtractedTask(BaseModel):
    content: str
    assignee_id: Optional[int]
    assignee_hint: str
    due_date: Optional[str]  # YYYY-MM-DD


class MinutesAnalysis(BaseModel):
    summary: str
    tasks: List[ExtractedTask]


def _client():
    # 키가 비어 있으면 SDK 가 환경변수(ANTHROPIC_API_KEY 등)에서 찾는다
    workspace_id = getattr(settings, 'ANTHROPIC_WORKSPACE_ID', '')
    return anthropic.Anthropic(
        api_key=settings.ANTHROPIC_API_KEY or None,
        timeout=300.0,
        # 워크스페이스에 묶이지 않은 키는 요청마다 이 헤더가 있어야 한다 (없으면 400)
        default_headers={'anthropic-workspace-id': workspace_id} if workspace_id else None,
    )


def analyze_minutes(**prompt_kwargs) -> MinutesAnalysis:
    """prompt_kwargs: build_minutes_user_prompt() 인자"""
    try:
        response = _client().messages.parse(
            model=settings.CLAUDE_MINUTES_MODEL,
            max_tokens=16000,
            system=MINUTES_SYSTEM_PROMPT,
            messages=[{'role': 'user', 'content': build_minutes_user_prompt(**prompt_kwargs)}],
            output_format=MinutesAnalysis,
        )
    except anthropic.AuthenticationError as e:
        raise AnalysisError('Claude API 키가 없거나 올바르지 않습니다.') from e
    except anthropic.PermissionDeniedError as e:
        raise AnalysisError('Claude API 키에 사용 권한이 없습니다. (크레딧 잔액을 확인해 주세요)') from e
    except anthropic.RateLimitError as e:
        raise AnalysisError('Claude API 사용 한도를 넘었습니다. 잠시 후 다시 분석해 주세요.') from e
    except anthropic.BadRequestError as e:
        raise AnalysisError(f'Claude API 요청 오류: {e.message}') from e
    except anthropic.APIStatusError as e:
        raise AnalysisError(f'Claude API 오류 ({e.status_code}). 잠시 후 다시 분석해 주세요.') from e
    except anthropic.APIConnectionError as e:
        raise AnalysisError('Claude API 서버에 연결하지 못했습니다.') from e

    if response.stop_reason == 'refusal':
        raise AnalysisError('AI 가 이 회의 내용의 분석을 거절했습니다.')
    if response.stop_reason == 'max_tokens':
        raise AnalysisError('회의 내용이 너무 길어 정리가 중간에 끊겼습니다.')
    if response.parsed_output is None:
        raise AnalysisError('AI 응답을 해석하지 못했습니다.')
    return response.parsed_output
