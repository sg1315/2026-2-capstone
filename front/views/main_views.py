from django.shortcuts import render

from .common import anonymous_only


# TODO css 스타일 가이드용 index입니다. 프로젝트 완료 후 삭제
def index(request):
    return render(request, 'index.html')


@anonymous_only
def main(request):
    """메인(랜딩) 페이지. 비로그인 전용 - 로그인 상태면 프로젝트 목록으로 이동"""
    return render(request, 'main/main.html')
