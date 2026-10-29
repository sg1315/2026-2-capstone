import os
import uuid

from django.db import models
from base.models import User


def project_upload_to(instance, filename):
    name = str(uuid.uuid4())
    ext = os.path.splitext(filename)[1]
    if isinstance(instance, Project):
        return 'attach/project/%d/%d/%s%s' % (int(instance.id / 10000), instance.id, name, ext)
    elif isinstance(instance, ProjectFile):
        return 'attach/project/%d/%d/%s%s' % (int(instance.project.id / 10000), instance.project.id, name, ext)
    return 'attach/project/etc/%s%s' % (name, ext)

class Project(models.Model):
    title = models.CharField('프로젝트명', max_length=2000, blank=False, null=False)
    content = models.TextField('내용', blank=True, null=True)
    start_at = models.DateField('프로젝트 시작일', blank=True, null=True)
    end_at = models.DateField('프로젝트 종료일', blank=True, null=True)

    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.RESTRICT, db_constraint=False, blank=True, null=True,
                                   related_name='+', verbose_name='생성자')
    updated_by = models.ForeignKey(User, on_delete=models.RESTRICT, db_constraint=False, blank=True, null=True,
                                   related_name='+', verbose_name='수정자')
    use_flag = models.BooleanField('사용 여부', max_length=1, blank=True, null=True, choices=[('N', 'N'), ('Y', 'Y'), ])

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'project'
        verbose_name = '프로젝트'
        verbose_name_plural = verbose_name


class UserProject(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT, db_constraint=False, verbose_name='사용자')
    project = models.ForeignKey(Project, on_delete=models.PROTECT, db_constraint=False, verbose_name='프로젝트')

    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.RESTRICT, db_constraint=False, blank=True, null=True,
                                   related_name='+', verbose_name='생성자')
    updated_by = models.ForeignKey(User, on_delete=models.RESTRICT, db_constraint=False, blank=True, null=True,
                                   related_name='+', verbose_name='수정자')
    use_flag = models.CharField('사용 여부', max_length=1, blank=True, default='Y', choices=[('N', 'N'), ('Y', 'Y'), ])

    class Meta:
        db_table = 'participant'
        verbose_name = '참여자'
        verbose_name_plural = verbose_name


class ProjectFile(models.Model):
    DOC_TYPE_CHOICES = [
        ('0', '개요'),
        ('1', '음성파일'),
    ]

    path = models.FileField('파일 경로', upload_to=project_upload_to, max_length=1000, blank=True, null=True)
    name = models.CharField('파일명', max_length=512, blank=True, null=True)
    type = models.CharField('파일 형식', max_length=128, blank=True, null=True)
    size = models.IntegerField('파일 크기', blank=True, null=True)
    doc_type = models.CharField('문서 형식', max_length=1, choices=DOC_TYPE_CHOICES, blank=True, null=True)

    created_at = models.DateTimeField('생성일시', auto_now_add=True)
    updated_at = models.DateTimeField('수정일시', auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.RESTRICT, db_constraint=False, blank=True, null=True,
                                   related_name='+', verbose_name='생성자')
    updated_by = models.ForeignKey(User, on_delete=models.RESTRICT, db_constraint=False, blank=True, null=True,
                                   related_name='+', verbose_name='수정자')
    use_flag = models.CharField('사용 여부', max_length=1, blank=True, default='Y', choices=[('N', 'N'), ('Y', 'Y'), ])

    @property
    def size_str(self):
        if not self.size:
            return "0 B"

        kb = 1024
        mb = kb * 1024
        gb = mb * 1024

        if self.size >= gb:
            return f"{self.size / gb:.1f} GB"
        elif self.size >= mb:
            return f"{self.size / mb:.1f} MB"
        elif self.size >= kb:
            return f"{self.size / kb:.1f} KB"
        else:
            return f"{self.size} B"

    class Meta:
        db_table = 'project_file'
        verbose_name = '프로젝트 첨부파일'
        verbose_name_plural = verbose_name