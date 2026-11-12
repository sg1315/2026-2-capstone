from django.db import models
from base.models import User
from base.models.minutes_models import Minutes


class Task(models.Model):
    minutes = models.ForeignKey(
        Minutes,
        on_delete=models.PROTECT,
        db_constraint=False,
        db_column='meeting_id',
        verbose_name='회의록'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        db_constraint=False,
        verbose_name='담당자'
    )
    content = models.TextField('업무 내용', blank=True, null=True)
    due_at = models.DateTimeField('마감일시', blank=True, null=True)
    complete_flag = models.CharField(
        '완료 여부',
        max_length=1,
        blank=True,
        null=True,
        default='N',
        choices=[('N', 'N'), ('Y', 'Y')]
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
    send_flag = models.CharField(
        '발송 여부',
        max_length=1,
        blank=True,
        null=True,
        choices=[('N', 'N'), ('Y', 'Y')]
    )

    class Meta:
        db_table = 'task'
        verbose_name = '업무'
        verbose_name_plural = verbose_name
