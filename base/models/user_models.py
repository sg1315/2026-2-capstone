from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    name = models.CharField('이름', max_length=50, blank=True, null=True)

    created_at = models.DateTimeField('등록일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)
    use_flag = models.BooleanField('사용 여부', max_length=1, blank=True, null=True, choices=[('N', 'N'), ('Y', 'Y'), ])
    session_key = models.CharField('현재 세션 키', max_length=50, blank=True, null=True)

    def __str__(self):
        return self.username

    class Meta:
        db_table = 'user'
        verbose_name = '사용자'
        verbose_name_plural = verbose_name
        ordering = ('-id',)