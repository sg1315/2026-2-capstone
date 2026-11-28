import os
import uuid

from django.db import models
from base.models import User
from base.models.project_models import Project


def minutes_upload_to(instance, filename):
    name = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1]

    if isinstance(instance, Minutes):
        return 'attach/minutes/%d/%d/%s%s' % (int(instance.id / 10000), instance.id, name, ext)
    elif isinstance(instance, MinutesFile):
        return 'attach/minutes/%d/%d/%s%s' % (int(instance.minutes.id / 10000), instance.minutes.id, name, ext)

    return 'attach/minutes/etc/%s%s' % (name, ext)


class Minutes(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        db_constraint=False,
        verbose_name='프로젝트'
    )
    title = models.CharField('회의록명', max_length=2000, blank=False, null=False)
    content = models.TextField('회의록 내용', blank=True, null=False, default='')  # 선택 입력. 있으면 AI 정리에 메모로 사용

    # AI 분석 (음성파일 -> Clova Speech 텍스트 변환 -> Claude 회의 정리 + 업무 추출). base/ai/pipeline.py
    AI_STATUS_CHOICES = [
        ('N', '분석 안 함'),
        ('W', '분석 대기'),
        ('R', '분석 중'),
        ('D', '분석 완료'),
        ('F', '분석 실패'),
    ]
    ai_status = models.CharField('AI 분석 상태', max_length=1, choices=AI_STATUS_CHOICES, default='N')
    ai_message = models.CharField('AI 분석 메시지', max_length=1000, blank=True, null=True)
    transcript = models.TextField('음성 변환 원문', blank=True, null=True)
    summary = models.TextField('AI 회의 정리', blank=True, null=True)

    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        db_constraint=False,
        blank=True,
        null=True,
        related_name='+',
        verbose_name='생성자'
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        db_constraint=False,
        blank=True,
        null=True,
        related_name='+',
        verbose_name='수정자'
    )
    use_flag = models.CharField(
        '사용 여부',
        max_length=1,
        blank=False,
        null=False,
        default='Y',
        choices=[('N', 'N'), ('Y', 'Y')]
    )

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'minutes'
        verbose_name = '회의록'
        verbose_name_plural = verbose_name


class MinutesFile(models.Model):
    DOC_TYPE_CHOICES = [
        ('0', '회의 자료'),   # 회의에 사용한 문서 (doc, ppt, excel, pdf 등)
        ('1', '음성파일'),    # 원본 녹음. AI 정리 결과는 Minutes.summary 에 저장
    ]

    minutes = models.ForeignKey(
        Minutes,
        on_delete=models.PROTECT,
        db_constraint=False,
        db_column='minutes_id',
        verbose_name='회의록'
    )
    path = models.FileField(
        '파일 경로',
        upload_to=minutes_upload_to,
        max_length=1000,
        blank=True,
        null=True
    )
    name = models.CharField('파일명', max_length=512, blank=True, null=True)
    type = models.CharField('파일 형식', max_length=128, blank=True, null=True)
    size = models.IntegerField('파일 크기', blank=True, null=True)
    doc_type = models.CharField(
        '문서 형식',
        max_length=1,
        choices=DOC_TYPE_CHOICES,
        blank=False,
        null=False
    )

    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        db_constraint=False,
        blank=True,
        null=True,
        related_name='+',
        verbose_name='생성자'
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        db_constraint=False,
        blank=True,
        null=True,
        related_name='+',
        verbose_name='수정자'
    )
    use_flag = models.CharField(
        '사용 여부',
        max_length=1,
        blank=False,
        null=False,
        default='Y',
        choices=[('N', 'N'), ('Y', 'Y')]
    )

    class Meta:
        db_table = 'minutes_file'
        verbose_name = '회의록 첨부파일'
        verbose_name_plural = verbose_name
