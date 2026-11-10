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
    content = models.TextField('회의록 내용', blank=False, null=False)

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
        ('0', '회의록 첨부파일'),
        ('1', '음성파일'),
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
