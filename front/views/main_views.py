from django.shortcuts import render


# TODO css 스타일 가이드용 index입니다. 프로젝트 완료 후 삭제
def index(request):
    return render(request, 'index.html')


def main(request):
    return render(request, 'main/main.html')