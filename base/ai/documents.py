"""
첨부 문서에서 텍스트 추출 -> Claude 에 참고 자료로 넘긴다.
  - 프로젝트 개요 (ProjectFile doc_type '0')      : 프로젝트 계획서 등 프로젝트 전체의 기반 문서 (목표, 기능, 역할 분담, 일정)
  - 회의 자료 (MinutesFile doc_type '0')            : 회의에서 함께 본 문서
지원: docx, pptx, xlsx, pdf, hwpx, txt, md, csv
미지원(건너뜀): doc, ppt, xls(구 바이너리 형식), hwp, 이미지 -> 새 형식(docx/pptx/xlsx)이나 pdf 로 저장해 올리면 읽을 수 있다
"""
import csv
import io
import logging
import os
import re
import zipfile

logger = logging.getLogger(__name__)

# 비용/응답 시간을 위한 상한. 넘으면 앞부분만 넣고 잘렸다고 프롬프트에 표시한다.
MAX_CHARS_PER_DOC = 30_000
MAX_CHARS_TOTAL = 120_000
MAX_SHEET_ROWS = 500

SUPPORTED_EXTENSIONS = {'.docx', '.pptx', '.xlsx', '.pdf', '.hwpx', '.txt', '.md', '.csv'}


def _decode(raw):
    for enc in ('utf-8-sig', 'cp949'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _docx(data):
    from docx import Document
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(' | '.join(cells))
    return '\n'.join(parts)


def _pptx(data):
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.extend(p.text for p in shape.text_frame.paragraphs if p.text.strip())
            if getattr(shape, 'has_table', False) and shape.has_table:
                for row in shape.table.rows:
                    texts.append(' | '.join(c.text.strip() for c in row.cells))
        if slide.has_notes_slide:
            note = slide.notes_slide.notes_text_frame.text.strip()
            if note:
                texts.append(f'(발표자 노트) {note}')
        if texts:
            parts.append(f'[슬라이드 {i}]\n' + '\n'.join(texts))
    return '\n\n'.join(parts)


def _xlsx(data):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        rows = []
        for n, row in enumerate(ws.iter_rows(values_only=True)):
            if n >= MAX_SHEET_ROWS:
                rows.append(f'(이하 행 생략: {MAX_SHEET_ROWS}행까지만 포함)')
                break
            cells = ['' if v is None else str(v).strip() for v in row]
            if any(cells):
                rows.append(' | '.join(cells).rstrip(' |'))
        if rows:
            parts.append(f'[시트: {ws.title}]\n' + '\n'.join(rows))
    wb.close()
    return '\n\n'.join(parts)


def _pdf(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or '').strip()
        if text:
            parts.append(f'[{i}쪽]\n{text}')
    return '\n\n'.join(parts)


def _hwpx(data):
    """hwpx = zip 안의 Contents/section*.xml. 문단(<hp:p>) 단위로 글자(<hp:t>)를 모은다."""
    parts = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sections = sorted(n for n in z.namelist() if re.match(r'Contents/section\d+\.xml$', n))
        for name in sections:
            xml = z.read(name).decode('utf-8', errors='replace')
            for para in re.findall(r'<hp:p\b.*?</hp:p>', xml, flags=re.S):
                text = ''.join(re.findall(r'<hp:t\b[^>]*>(.*?)</hp:t>', para, flags=re.S))
                text = re.sub(r'<[^>]+>', '', text).strip()
                if text:
                    parts.append(text)
    return '\n'.join(parts)


def _csv(data):
    rows = list(csv.reader(io.StringIO(_decode(data))))[:MAX_SHEET_ROWS]
    return '\n'.join(' | '.join(r) for r in rows if any(r))


EXTRACTORS = {
    '.docx': _docx, '.pptx': _pptx, '.xlsx': _xlsx, '.pdf': _pdf, '.hwpx': _hwpx,
    '.csv': _csv, '.txt': lambda d: _decode(d), '.md': lambda d: _decode(d),
}


def extract_text(file_field, filename):
    """-> (텍스트 또는 None, 건너뛴 이유 또는 None)"""
    ext = os.path.splitext(filename or '')[1].lower()
    extractor = EXTRACTORS.get(ext)
    if not extractor:
        return None, '읽을 수 없는 형식'
    try:
        with file_field.open('rb') as f:
            text = extractor(f.read())
    except Exception:
        logger.warning('문서 텍스트 추출 실패: %s', filename, exc_info=True)
        return None, '파일을 읽지 못함'
    text = re.sub(r'\n{3,}', '\n\n', text or '').strip()
    if not text:
        return None, '글자가 없음 (스캔 이미지 PDF 등)'
    return text, None


def collect_documents(files):
    """
    files: [(출처 라벨, FileField, 파일명), ...] 앞에 있는 것부터 우선 포함
    -> (documents, skipped)
       documents: [{'source', 'name', 'text', 'truncated'}]
       skipped:   ['파일명 (이유)']
    """
    documents, skipped = [], []
    remaining = MAX_CHARS_TOTAL
    for source, file_field, name in files:
        if remaining <= 0:
            skipped.append(f'{name} (참고 자료 분량 초과)')
            continue
        text, reason = extract_text(file_field, name)
        if text is None:
            skipped.append(f'{name} ({reason})')
            continue
        limit = min(MAX_CHARS_PER_DOC, remaining)
        truncated = len(text) > limit
        text = text[:limit]
        remaining -= len(text)
        documents.append({'source': source, 'name': name, 'text': text, 'truncated': truncated})
    return documents, skipped
